"""Frame-rate independent springs, kept from the two reference islands.

A target can change at any frame: the current position and speed carry over,
so reversing an opening into a closing bends instead of jumping.
"""
import math


class Spring:
    def __init__(self, value: float, stiffness: float, ratio: float, epsilon: float = 0.05):
        self.value = self.target = float(value)
        self.velocity = 0.0
        self.epsilon = epsilon
        self.tune(stiffness, ratio)

    def tune(self, stiffness: float, ratio: float) -> None:
        self.k = float(stiffness)
        self.c = 2.0 * float(ratio) * math.sqrt(self.k)

    def snap(self, value: float) -> None:
        self.value = self.target = float(value)
        self.velocity = 0.0

    def step(self, dt: float) -> bool:
        dt = min(max(dt, 0.0), 0.1)
        n = max(1, int(math.ceil(dt * 480.0)))
        h = dt / n
        for _ in range(n):
            accel = -self.k * (self.value - self.target) - self.c * self.velocity
            self.velocity += accel * h
            self.value += self.velocity * h
        return self.moving()

    def moving(self) -> bool:
        return (abs(self.value - self.target) > self.epsilon
                or abs(self.velocity) > self.epsilon * 10.0)
