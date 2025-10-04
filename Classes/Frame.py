import cv2
import numpy as np


class Frame:
    def __init__(self, frame : np.ndarray, sift : cv2.SIFT, down_sample : int):
        self.frame = frame
        self.down_sample = down_sample
        self.shape = None
        self.valid_matches = None
        self.valid_features = None
        self.valid_descriptors = None

        if self.frame is not None:
            if down_sample != 1:
                self.frame = cv2.resize(self.frame, (self.frame.shape[1] // down_sample, self.frame.shape[0] // down_sample))
            self.shape = frame.shape
            self.features, self.descriptor = self.process_frame(sift)

    def process_frame(self, sift : cv2.SIFT):
        features, descriptor = sift.detectAndCompute(self.frame, None)
        return features, descriptor

    def update_valid(self, valid_matches, valid_features, valid_descriptors):
        self.valid_matches = valid_matches
        self.valid_features = valid_features
        self.valid_descriptors = valid_descriptors
