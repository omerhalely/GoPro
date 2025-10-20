import matplotlib.pyplot as plt
import numpy as np

from OfflineFiltering.Classes.KalmanFilter import KalmanFilter


class Trajectory:
    def __init__(self, time, filter_window_size=5):
        self.time = time
        self.filter_window_size = filter_window_size

        self.R = np.eye(3, dtype=np.float32)
        self.t = np.zeros((3, 1), dtype=np.float32)
        self.trajectory = np.array([0, 0, 0]).reshape(1, 3)
        self.velocity = np.array([]).reshape(0, 3)

        self.KF = KalmanFilter()

    def update(self, R: np.ndarray, t: np.ndarray, dt: float, s=1, valid=True):
        self.t = self.t + s * self.R @ t
        self.R = self.R @ R

        filtered_trajectory = self.KF.process(dt, self.t, valid)
        self.trajectory = np.concatenate((self.trajectory, filtered_trajectory.T))

        velocity = 3.6 * (self.trajectory[-1, :] - self.trajectory[-2, :]) / dt
        velocity = velocity.reshape(1, 3)
        self.velocity = np.concatenate((self.velocity, velocity))
        start_index = max(0, self.velocity.shape[0] - self.filter_window_size)
        filtered_velocity = np.mean(self.velocity[start_index:, :], axis=0)
        self.velocity[-1, :] = filtered_velocity


    def plot_trajectory(self, axis : str="xz"):
        assert axis == "xy" or axis == "xz" or axis == "yz", "Axis must be xy || xz || yz"

        if axis == "xy":
            plt.plot(self.trajectory[:, 0], self.trajectory[:, 1])
            plt.xlabel("X")
            plt.ylabel("Y")
        elif axis == "xz":
            plt.plot(self.trajectory[:, 0], self.trajectory[:, 2])
            plt.xlabel("X")
            plt.ylabel("Z")
        elif axis == "yz":
            plt.plot(self.trajectory[:, 1], self.trajectory[:, 2])
            plt.xlabel("Y")
            plt.ylabel("Z")

    def plot_velocity(self):
        total_velocity = np.linalg.norm(self.velocity, axis=-1)
        plt.plot(total_velocity)
