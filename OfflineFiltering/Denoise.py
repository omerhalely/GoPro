import os
from pathlib import Path
import cv2
import bm3d
import matplotlib.pyplot as plt
import numpy as np


# -------------------------
# 1) Warp maps (output -> reference)
# -------------------------
def build_warp_maps(H, H_img, W_img):
    """
    Given homography H mapping output pixel (u,v,1)^T -> reference (x',y'),
    build dense float maps X,Y of reference coords for each output pixel.
    Returns X,Y as float32 and a boolean mask of in-bounds source coords.
    """
    # grid of output pixels (u,v)
    u, v = np.meshgrid(np.arange(W_img), np.arange(H_img))  # (H,W)
    ones = np.ones_like(u, dtype=np.float64)

    U = np.stack([u, v, ones], axis=0).reshape(3, -1)  # 3 x (H*W)
    HW = H @ U                                         # 3 x (H*W)

    X = (HW[0] / HW[2]).reshape(H_img, W_img)
    Y = (HW[1] / HW[2]).reshape(H_img, W_img)

    # source (reference) bounds
    mask = (X >= 0) & (X <= (W_img - 1)) & (Y >= 0) & (Y <= (H_img - 1))

    return X.astype(np.float32), Y.astype(np.float32), mask

# -------------------------
# 2) Apply W (backward warping via remap)
# -------------------------
def warp_apply(x, mapX, mapY, mask=None):
    """
    y = W x  using cv2.remap (bilinear). Outside-mask samples -> 0.
    x: (H,W) float32
    mapX, mapY: float32 maps from build_warp_maps
    """
    y = cv2.remap(x, mapX, mapY, interpolation=cv2.INTER_LINEAR,
                  borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if mask is not None:
        y = y * mask.astype(np.float32)
    return y

# -------------------------
# 3) Apply W^T (adjoint = splatting)
# -------------------------
def warp_apply_adjoint(y, mapX, mapY, H_img, W_img, mask=None):
    """
    z = W^T y  (bilinear splat back to reference grid).
    Uses np.add.at to accumulate contributions.
    y: (H,W) sampled on the output grid (same size as reference for simplicity)
    """
    if mask is not None:
        y = y * mask.astype(np.float32)

    # source coords (X,Y) in reference image (float)
    X = mapX.astype(np.float64)
    Y = mapY.astype(np.float64)

    # integer floors and fractional parts
    x0 = np.floor(X).astype(np.int64)
    y0 = np.floor(Y).astype(np.int64)
    ax = X - x0
    ay = Y - y0

    x1 = x0 + 1
    y1 = y0 + 1

    # neighbor weights
    w00 = (1 - ax) * (1 - ay)
    w10 = (ax)     * (1 - ay)
    w01 = (1 - ax) * (ay)
    w11 = (ax)     * (ay)

    # validity of each neighbor inside source bounds
    def inside(ix, iy):
        return (ix >= 0) & (ix < W_img) & (iy >= 0) & (iy < H_img)

    H, W = H_img, W_img
    z = np.zeros((H, W), dtype=np.float64)

    # flatten indices for np.add.at
    yy = np.arange(H)[:, None].repeat(W, axis=1)
    xx = np.arange(W)[None, :].repeat(H, axis=0)

    # Each output pixel (yy,xx) contributes y*weight to source pixels (y*,x*)
    for (xn, yn, wn) in [(x0, y0, w00), (x1, y0, w10), (x0, y1, w01), (x1, y1, w11)]:
        m = inside(xn, yn)
        if mask is not None:
            m = m & mask
        if not np.any(m):
            continue
        # target indices in reference grid
        tgt_y = yn[m]
        tgt_x = xn[m]
        contrib = (y[m] * wn[m]).ravel()
        # accumulate
        np.add.at(z, (tgt_y, tgt_x), contrib)

    return z.astype(np.float32)

# -------------------------
# 4) Laplacian and biharmonic (Δ^T Δ)
# -------------------------
_LAPL_KER = np.array([[0, 1, 0],
                      [1, -4, 1],
                      [0, 1, 0]], dtype=np.float32)

def laplacian(img):
    # Neumann-like (replicate) borders to avoid dark rims
    return cv2.filter2D(img, ddepth=cv2.CV_32F, kernel=_LAPL_KER, borderType=cv2.BORDER_REPLICATE)

def biharmonic(img):
    # Δ^T Δ with symmetric Laplacian -> apply twice
    return laplacian(laplacian(img))

# -------------------------
# 5) A x  and  b
# -------------------------
def A_apply(x, maps, lam):
    """
    A x = sum_i W_i^T W_i x + lam * Δ^TΔ x
    maps: list of (mapX_i, mapY_i, mask_i)
    """
    acc = np.zeros_like(x, dtype=np.float32)
    for (mapX, mapY, mask) in maps:
        y = warp_apply(x, mapX, mapY, mask)          # W x
        z = warp_apply_adjoint(y, mapX, mapY, *x.shape, mask)  # W^T (W x)
        acc += z
    if lam != 0.0:
        acc += lam * biharmonic(x)
    return acc

def build_rhs(y_frames, maps):
    """
    b = sum_i W_i^T y_i
    y_frames: list of (H,W) float32 frames in output geometry (same size)
    """
    b = np.zeros_like(y_frames[0], dtype=np.float32)
    for yi, (mapX, mapY, mask) in zip(y_frames, maps):
        b += warp_apply_adjoint(yi, mapX, mapY, *yi.shape, mask)
    return b

# -------------------------
# 6) Conjugate Gradient (NumPy)
# -------------------------
def cg(Aop, b, x0=None, max_iter=80, tol=1e-4):
    x = np.zeros_like(b, dtype=np.float32) if x0 is None else x0.astype(np.float32).copy()
    r = b - Aop(x)
    p = r.copy()
    rsold = float(np.vdot(r, r))
    if rsold == 0.0:
        return x
    for _ in range(max_iter):
        Ap = Aop(p)
        denom = float(np.vdot(p, Ap))
        if denom == 0.0:
            break
        alpha = rsold / denom
        x = x + alpha * p
        r = r - alpha * Ap
        rsnew = float(np.vdot(r, r))
        if np.sqrt(rsnew) < tol:
            break
        p = r + (rsnew / rsold) * p
        rsold = rsnew
    return x

# -------------------------
# 7) Top-level solver
# -------------------------
def denoise_reference_frame(y_frames, H_list, lam=0.02, max_iter=80, tol=1e-4, x0=None):
    """
    y_frames: list of (H,W) float32 frames (noisy), all same shape
    H_list:   list of 3x3 float64 homographies mapping (u,v,1) in output -> reference coords
              (i.e., backward maps). If you estimated ref->output, use np.linalg.inv once.
    lam: regularization weight for Laplacian prior
    x0: optional warm-start (H,W) float32
    Returns: x_hat (H,W) float32
    """
    H_img, W_img = y_frames[0].shape
    # build maps once
    maps = [build_warp_maps(H, H_img, W_img) for H in H_list]

    # right-hand side
    b = build_rhs(y_frames, maps)

    # operator
    Aop = lambda x: A_apply(x, maps, lam)

    # optional better warm start: motion-compensated average
    if x0 is None:
        # denom ~ sum W^T W 1
        ones = np.ones_like(b, dtype=np.float32)
        denom = np.zeros_like(b, dtype=np.float32)
        num = np.zeros_like(b, dtype=np.float32)
        for yi, (mapX, mapY, mask) in zip(y_frames, maps):
            num   += warp_apply_adjoint(yi,   mapX, mapY, H_img, W_img, mask)
            denom += warp_apply_adjoint(ones, mapX, mapY, H_img, W_img, mask)
        denom = np.maximum(denom, 1e-6)
        x0 = num / denom

    # x_hat = cg(Aop, b, x0=x0, max_iter=max_iter, tol=tol)
    x_hat = x0
    return x_hat


def get_homography(frames):
    frames = [np.asarray(np.clip(frames[i], 0, 1) * 255, dtype=np.uint8) for i in range(len(frames))]
    sift = cv2.SIFT_create(nfeatures=4000)
    index_params = dict(algorithm=1, trees=5)  # KDTree
    search_params = dict(checks=50)
    flann = cv2.FlannBasedMatcher(index_params, search_params)

    H = [np.eye(3)]
    k1, d1 = sift.detectAndCompute(frames[0], None)
    for i in range(1, len(frames)):
        k2, d2 = sift.detectAndCompute(frames[i], None)

        knn = flann.knnMatch(d1, d2, k=2)
        good = []
        for m, n in knn:
            if m.distance < 0.75 * n.distance:
                good.append(m)

        pts1 = np.float32([k1[m.queryIdx].pt for m in good])
        pts2 = np.float32([k2[m.trainIdx].pt for m in good])

        Hi, mask = cv2.findHomography(pts2, pts1, method=cv2.RANSAC, ransacReprojThreshold=0.99)
        H.append(Hi)

    return H


def sharp_image(image, method, ksize, std, alpha):
    if method == "Gaussian":
        x_hat_smooth = cv2.GaussianBlur(image, ksize=(ksize, ksize), sigmaX=std, sigmaY=std)
    elif method == "median":
        x_hat_smooth = cv2.medianBlur(image, ksize=ksize)

    x_hat_smooth = np.asarray(x_hat_smooth, dtype=np.float32)
    detail = image - x_hat_smooth

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 1.2)
    edges = cv2.Canny((blur * 255).astype(np.uint8), 80, 160)
    edges = edges.astype(np.float32) / 255.0  # 0–1 mask

    edges = cv2.dilate(edges, (5, 5), cv2.MORPH_ELLIPSE, iterations=5)
    edges = edges[..., None]

    x_hat_sharp = np.asarray(np.clip(image + alpha * detail * edges, 0, 255), dtype=np.uint8)
    return x_hat_sharp

# -------------------------
# 8) Example usage (toy)
# -------------------------
if __name__ == "__main__":
    parent = os.path.abspath(os.path.join(os.getcwd(), ".."))
    path = os.path.join(parent, "RaspberryPi", "outputs", "14-10-2025", "videos", "output.avi")
    cap = cv2.VideoCapture(path)

    fps = cap.get(cv2.CAP_PROP_FPS)

    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # size = (width, height)

    # fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # "mp4v" works for .mp4 on most setups
    # out = cv2.VideoWriter("Filtered.mp4", fourcc, fps, size)
    frames_R = []
    frames_G = []
    frames_B = []

    noisy_frames_R = []
    noisy_frames_G = []
    noisy_frames_B = []
    N = 5
    std = 0
    for i in range(N):
        ret, frame = cap.read()

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        frame_R = frame[:, :, 0]
        frame_G = frame[:, :, 1]
        frame_B = frame[:, :, 2]

        frame_R = (frame_R - np.min(frame_R)) / (np.max(frame_R) - np.min(frame_R))
        frame_G = (frame_G - np.min(frame_G)) / (np.max(frame_G) - np.min(frame_G))
        frame_B = (frame_B - np.min(frame_B)) / (np.max(frame_B) - np.min(frame_B))

        noise_R = std * np.random.randn(*frame_R.shape)
        noise_G = std * np.random.randn(*frame_G.shape)
        noise_B = std * np.random.randn(*frame_B.shape)

        noisy_R = frame_R + noise_R
        noisy_G = frame_G + noise_G
        noisy_B = frame_B + noise_B

        frames_R.append(frame_R)
        frames_G.append(frame_G)
        frames_B.append(frame_B)

        noisy_frames_R.append(noisy_R)
        noisy_frames_G.append(noisy_G)
        noisy_frames_B.append(noisy_B)

    H_list = get_homography(noisy_frames_R)

    lam = 1
    x_hat_R = denoise_reference_frame(noisy_frames_R, H_list, lam=lam, max_iter=60, tol=1e-5)
    x_hat_G = denoise_reference_frame(noisy_frames_G, H_list, lam=lam, max_iter=60, tol=1e-5)
    x_hat_B = denoise_reference_frame(noisy_frames_B, H_list, lam=lam, max_iter=60, tol=1e-5)

    noisy_frame = np.concatenate((frames_R[0][..., np.newaxis], frames_G[0][..., np.newaxis], frames_B[0][..., np.newaxis]), axis=-1)
    x_hat = np.concatenate((x_hat_R[..., np.newaxis], x_hat_G[..., np.newaxis], x_hat_B[..., np.newaxis]), axis=-1)

    x_hat = np.asarray(np.clip(x_hat * 255, 0, 255), dtype=np.uint8)

    method = "Gaussian"
    ksize = 7
    std = (ksize - 1) / 6
    alpha = 1.5

    x_hat_sharp = sharp_image(x_hat, method, ksize, std, alpha)

    fig, axis = plt.subplots(1, 2)
    axis[0].imshow(x_hat)
    axis[1].imshow(x_hat_sharp)
    plt.show()
