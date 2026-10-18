"""Small CPU texture renderer. No microphone, screen or system-audio access."""
import math
import numpy as np
from PIL import Image


class SunTexture:
    def __init__(self, path, resolution=300):
        self.n = resolution
        im = Image.open(path).convert('RGBA').resize((resolution, resolution), Image.Resampling.LANCZOS)
        src = np.asarray(im, dtype=np.float32) / 255.0
        y, x = np.mgrid[:resolution, :resolution].astype(np.float32)
        self.x = (x - (resolution - 1) / 2) / (resolution / 2)
        self.y = (y - (resolution - 1) / 2) / (resolution / 2)
        self.r = np.hypot(self.x, self.y)
        self.a = np.arctan2(self.y, self.x)
        # Preserve the dense solar disk. Unmatte the black exterior smoothly.
        disk = np.clip((0.585 - self.r) / 0.055, 0, 1)
        maximum = src[:, :, :3].max(axis=2)
        exterior = np.clip((maximum - 0.028) / 0.972, 0, 1)
        alpha = np.maximum(disk, exterior) * src[:, :, 3]
        rgb = np.clip((src[:, :, :3] - 0.012) / np.maximum(alpha[:, :, None], 0.015), 0, 1)
        # Premultiplication avoids dark seams in interpolation and compositing.
        self.texture = np.dstack((rgb * alpha[:, :, None], alpha)).astype(np.float32)
        # Sample the alpha once at the fixed display scale, never deform it.
        u = np.clip((self.x / 0.905 + 1) * resolution / 2 - 0.5, 0, resolution - 1.001)
        v = np.clip((self.y / 0.905 + 1) * resolution / 2 - 0.5, 0, resolution - 1.001)
        xi, yi = u.astype(np.int32), v.astype(np.int32)
        fx, fy = u - xi, v - yi
        self.fixed_alpha = ((alpha[yi, xi] * (1-fx) + alpha[yi, xi+1] * fx) * (1-fy)
                            + (alpha[yi+1, xi] * (1-fx) + alpha[yi+1, xi+1] * fx) * fy)


    def frame(self, t, energy=0.25, voice=0.0, motion=1.0):
        """Return uint8 premultiplied RGBA; t is continuous animation time."""
        breath = math.sin(t * 1.25)
        # Fixed position, scale and silhouette; deformation stays inside the disk.
        r = self.r / 0.905
        inner = np.clip((0.565 - r) / 0.16, 0, 1)
        inner = inner * inner * (3 - 2 * inner)
        flow = t * motion
        angle = self.a + inner * (
            0.105 * np.sin(flow * 0.65 - r * 7)
            + 0.038 * np.sin(self.a * 3 + flow * 0.43 + r * 9))
        radius = r * (1 + inner * 0.018 * np.sin(self.a * 4 - flow * 0.8 + r * 8))
        u = np.clip((radius * np.cos(angle) + 1) * self.n / 2 - 0.5, 0, self.n - 1.001)
        v = np.clip((radius * np.sin(angle) + 1) * self.n / 2 - 0.5, 0, self.n - 1.001)
        xi, yi = u.astype(np.int32), v.astype(np.int32)
        fx, fy = (u - xi).astype(np.float32)[:, :, None], (v - yi).astype(np.float32)[:, :, None]
        tex = self.texture
        out = ((tex[yi, xi] * (1 - fx) + tex[yi, xi + 1] * fx) * (1 - fy)
               + (tex[yi + 1, xi] * (1 - fx) + tex[yi + 1, xi + 1] * fx) * fy)
        brightness = 0.35 + 0.53 * energy + 0.11 * voice + 0.018 * breath
        shimmer = 1 + 0.045 * inner * np.sin(self.a * 4 + r * 13 - t * 0.9)
        out[:, :, :3] *= brightness * shimmer[:, :, None]
        out[:, :, 3] = self.fixed_alpha * (0.83 + 0.17 * energy)
        out[:, :, :3] = np.minimum(out[:, :, :3], out[:, :, 3:4])
        return np.ascontiguousarray(np.clip(out * 255, 0, 255).astype(np.uint8))
