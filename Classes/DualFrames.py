import cv2
import numpy as np

from Classes.Frame import Frame


class DualFrames:
    def __init__(
            self,
            left_frame : np.ndarray | None,
            right_frame : np.ndarray | None,
            K : np.ndarray,
            P_00 : np.ndarray,
            P_10 : np.ndarray,
            sift : cv2.SIFT,
            bf : cv2.BFMatcher,
            down_sample : int
    ):
        self.left_frame = Frame(left_frame, sift, down_sample)
        self.right_frame = Frame(right_frame, sift, down_sample)
        self.K = K
        self.P_00 = P_00
        self.P_10 = P_10
        self.sift = sift
        self.bf = bf
        self.down_sample = down_sample

        self.K *= 1 / down_sample
        self.K[2][2] = 1

        self.world_coordinates = None

    def copy(self, other : "DualFrames"):
        self.left_frame = other.left_frame
        self.right_frame = other.right_frame

    def update_frames(self, left_frame : np.ndarray, right_frame : np.ndarray):
        self.left_frame = Frame(left_frame, self.sift, self.down_sample)
        self.right_frame = Frame(right_frame, self.sift, self.down_sample)

    def solve_stereo(self, t=0.75):
        matches = self.bf.knnMatch(self.left_frame.descriptor, self.right_frame.descriptor, k=2)
        left_valid_matches = []
        right_valid_matches = []
        left_valid_features = []
        right_valid_features = []
        left_valid_descriptors = []
        right_valid_descriptors = []
        for m, n in matches:
            if m.distance < t * n.distance:
                left_valid_matches.append(self.left_frame.features[m.queryIdx].pt)
                right_valid_matches.append(self.right_frame.features[m.trainIdx].pt)

                left_valid_features.append(self.left_frame.features[m.queryIdx])
                right_valid_features.append(self.right_frame.features[m.trainIdx])

                left_valid_descriptors.append(self.left_frame.descriptor[m.queryIdx])
                right_valid_descriptors.append(self.right_frame.descriptor[m.trainIdx])

        left_valid_matches = np.array(left_valid_matches, dtype=np.float32).T
        right_valid_matches = np.array(right_valid_matches, dtype=np.float32).T

        left_valid_features = np.array(left_valid_features)
        right_valid_features = np.array(right_valid_features)

        left_valid_descriptors = np.array(left_valid_descriptors)
        right_valid_descriptors = np.array(right_valid_descriptors)

        world_coordinates = cv2.triangulatePoints(self.P_00, self.P_10, left_valid_matches, right_valid_matches)
        world_coordinates = world_coordinates / world_coordinates[-1, :]
        world_coordinates = world_coordinates.T
        norm = np.linalg.norm(world_coordinates, axis=-1)

        mask = norm < 80
        world_coordinates = world_coordinates[mask]
        self.world_coordinates = world_coordinates

        left_valid_matches = left_valid_matches[:, mask]
        left_valid_features = tuple(left_valid_features[mask])
        left_valid_descriptors = left_valid_descriptors[mask]
        right_valid_matches = right_valid_matches[:, mask]
        right_valid_features = tuple(right_valid_features[mask])
        right_valid_descriptors = right_valid_descriptors[mask]

        self.left_frame.update_valid(left_valid_matches, left_valid_features, left_valid_descriptors)
        self.right_frame.update_valid(right_valid_matches, right_valid_features, right_valid_descriptors)

    def find_homography(self):
        H, inlier_mask = cv2.findHomography(
            self.left_frame.valid_matches.T, self.right_frame.valid_matches.T,
            method=cv2.RANSAC,
            ransacReprojThreshold=0.1,
            maxIters=2000,
            confidence=0.999
        )
        return H
