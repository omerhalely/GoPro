import cv2
import numpy as np
import pykitti
import os
import matplotlib.pyplot as plt
from tqdm import tqdm

from utils import build_reference_trajectory
from Classes.DualFrames import DualFrames
from Classes.Trajectory import Trajectory
from Classes.KalmanFilter import KalmanFilter


def R_t_estimation(prev_frames : DualFrames, current_frames : DualFrames, bf : cv2.BFMatcher, t=0.75):
    prev_frame = prev_frames.left_frame
    current_frame = current_frames.left_frame

    matches = bf.knnMatch(prev_frame.descriptor, current_frame.descriptor, k=2)

    current_valid_match = []
    prev_valid_match = []
    for m, n in matches:
        if m.distance < t * n.distance:
            prev_valid_match.append(prev_frame.features[m.queryIdx].pt)
            current_valid_match.append(current_frame.features[m.trainIdx].pt)

    current_valid_match = np.array(current_valid_match)
    prev_valid_match = np.array(prev_valid_match)

    F, mask = cv2.findFundamentalMat(current_valid_match, prev_valid_match, cv2.FM_RANSAC, 0.1, 0.999)

    K = prev_frames.K
    E = K.T @ F @ K

    _, R, t, _ = cv2.recoverPose(E, current_valid_match, prev_valid_match, cameraMatrix=K)

    U, S, VT = np.linalg.svd(E)
    S = sorted(S.tolist())
    valid = True
    if S[1] < 100:
        valid = False

    return R, t, valid


def find_corresponding_points(left_frame : np.ndarray, right_frame : np.ndarray, x, y, window_size=5):
    center_window = left_frame[y - window_size // 2:y + window_size // 2, x - window_size // 2:x + window_size // 2]
    max_p = 0
    best_j = x
    for j in range(x, window_size // 2, -1):
        current_window = right_frame[y - window_size // 2:y + window_size // 2, j - window_size // 2:j + window_size // 2]
        p = np.exp(-np.mean(np.abs(center_window - current_window)))

        if p > max_p:
            max_p = p
            best_j = j

    return best_j


def visual_odometry(dataset : pykitti.raw):
    ENU, NED, time = build_reference_trajectory(dataset)

    trajectory = Trajectory(time)
    trajectory2 = Trajectory(time)

    calibration_data = dataset.calib
    sift = cv2.SIFT_create(
        nfeatures=800,
        nOctaveLayers=2,
        edgeThreshold=12,
        sigma=1.6
    )

    bf = cv2.BFMatcher()
    left_frame = np.array(dataset.get_cam0(0))
    right_frame = np.array(dataset.get_cam1(0))

    down_sample = 1
    prev_frames = DualFrames(
        left_frame=left_frame,
        right_frame=right_frame,
        K=calibration_data.K_cam1,
        P_00=calibration_data.P_rect_00,
        P_10=calibration_data.P_rect_10,
        sift=sift,
        bf=bf,
        down_sample=down_sample
    )

    current_frames = DualFrames(
        left_frame=None,
        right_frame=None,
        K=calibration_data.K_cam1,
        P_00=calibration_data.P_rect_00,
        P_10=calibration_data.P_rect_10,
        sift=sift,
        bf=bf,
        down_sample=down_sample
    )

    KF = KalmanFilter()

    prev_gt_pose = ENU[:, 0]

    lk_params = dict(
        winSize=(11, 11),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01)
    )

    current_time = time[0]
    for i in tqdm(range(1, len(dataset) // 5)):
        dt = (time[i] - current_time).total_seconds()
        current_time = time[i]

        left_frame = np.array(dataset.get_cam0(i))
        right_frame = np.array(dataset.get_cam1(i))
        current_frames.update_frames(
            left_frame=left_frame,
            right_frame=right_frame
        )

        prev_frames.solve_stereo()

        left_prev_points = prev_frames.left_frame.valid_matches.T
        prev_world_coordinates = prev_frames.world_coordinates
        left_next_pts, left_status, err = cv2.calcOpticalFlowPyrLK(
            prev_frames.left_frame.frame,
            current_frames.left_frame.frame,
            left_prev_points,
            None,
            **lk_params
        )

        right_prev_points = prev_frames.right_frame.valid_matches.T
        right_next_pts, right_status, err = cv2.calcOpticalFlowPyrLK(
            prev_frames.right_frame.frame,
            current_frames.right_frame.frame,
            right_prev_points,
            None,
            **lk_params
        )

        status = np.logical_and(left_status, right_status)
        left_good_new = left_next_pts[status.flatten() == 1].reshape(-1, 1, 2)
        right_good_new = right_next_pts[status.flatten() == 1].reshape(-1, 1, 2)
        prev_world_coordinates = prev_world_coordinates[status.flatten() == 1]

        world_coordinates = cv2.triangulatePoints(current_frames.P_00, current_frames.P_10, left_good_new, right_good_new)
        world_coordinates = world_coordinates / world_coordinates[-1, :]
        world_coordinates = world_coordinates.T
        norm = np.linalg.norm(world_coordinates, axis=-1)
        mask = norm < 80
        world_coordinates = world_coordinates[mask]
        prev_world_coordinates = prev_world_coordinates[mask]

        d = world_coordinates[:, [0, 2]] - prev_world_coordinates[:, [0, 2]]
        d = np.linalg.norm(d, axis=-1)
        max_velocity = 50
        d = d[d < max_velocity * 0.1]
        scale = np.median(d)

        R, t, valid = R_t_estimation(
            prev_frames=prev_frames,
            current_frames=current_frames,
            bf=bf
        )

        current_gt_pose = ENU[:, i]
        scale2 = np.linalg.norm(current_gt_pose - prev_gt_pose) / np.linalg.norm(t)

        prev_gt_pose = current_gt_pose

        trajectory.update(R, t, dt, s=scale, valid=valid)
        trajectory2.update(R, t, dt, s=scale2)

        prev_frames.copy(current_frames)

    plt.figure()
    trajectory.plot_trajectory()
    trajectory2.plot_trajectory()

    plt.figure()
    trajectory.plot_velocity()
    trajectory2.plot_velocity()

    plt.show()


if __name__ == "__main__":
    basedir = os.path.join(os.getcwd(), "data")
    date = "2011_09_26"
    drive = "0061"

    dataset = pykitti.raw(basedir, date, drive)

    visual_odometry(
        dataset=dataset
    )
