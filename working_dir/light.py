import numpy as np
import math
import random
theta = 3 * random.random()
amp = 1 + random.random()
for z in np.arange(1.0, -0.0001, -0.005):
    x = math.sqrt(1 - z ** 2) * math.cos(theta)
    y = math.sqrt(1 - z ** 2) * math.sin(theta)
    theta += amp
    print(f'{x} {y} {z}')