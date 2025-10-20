import numpy as np


class KalmanFilter:
    def __init__(self):
        self.x = np.zeros((6, 1))
        self.P = np.eye(6)

        self.dt = 0.1
        self.A = np.array([
            [1, 0, 0, self.dt, 0, 0],
            [0, 1, 0, 0, self.dt, 0],
            [0, 0, 1, 0, 0, self.dt],
            [0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 1]
        ])
        self.Q = 0.01 * np.eye(6)
        self.R = 0.001 * np.eye(3)
        self.H = np.array([
            [1, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0]
        ])

    def update_model(self, dt):
        self.dt = dt
        self.A[0, 3] = self.dt
        self.A[1, 4] = self.dt
        self.A[2, 5] = self.dt

    def predict(self, dt):
        self.update_model(dt)
        self.x = self.A @ self.x
        self.P = self.A @ self.P @ self.A.T + self.Q

    def update(self, z):
        y = z - self.H @ self.x
        s = self.H @ self.P @ self.H.T + self.R
        k = self.P @ self.H.T @ np.linalg.inv(s)
        self.x = self.x + k @ y
        self.P = (np.eye(6) - k @ self.H) @ self.P

    def process(self, dt, z, valid):
        self.predict(dt)

        if valid:
            self.update(z)

        return self.x[:3, :]
