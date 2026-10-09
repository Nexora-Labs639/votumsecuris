"""
图标生成脚本（模仿英伟达：绿色 + 斜眼漩涡 + 盾牌）
生成：icon.png (512) + icon.ico (Windows)
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent
SIZE = 512

NV_GREEN = (118, 185, 0)
NV_GREEN_DARK = (78, 122, 0)
BG = (13, 17, 23)


def draw_icon():
    img = Image.new("RGBA", (SIZE, SIZE), BG + (255,))
    draw = ImageDraw.Draw(img)
    cx, cy = SIZE // 2, SIZE // 2

    # ========== 1. 斜眼外框（用多边形模拟） ==========
    # 眼睛的两条弧：上弧 + 下弧，交点形成眼形
    # 上弧：从左到右向上弯
    # 下弧：从左到右向下弯
    # 用多边形近似，倾斜 -25 度

    angle = math.radians(-25)
    cos_a, sin_a = math.cos(angle), math.sin(angle)

    def rotate(x, y):
        # 绕中心旋转
        dx, dy = x - cx, y - cy
        return cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a

    # 眼睛的外轮廓点（未旋转）
    w, h = 180, 80
    left, right = cx - w, cx + w
    top, bottom = cy - h, cy + h

    # 上弧（控制点在上方）
    upper_pts = []
    steps = 30
    for i in range(steps + 1):
        t = i / steps
        # 二次贝塞尔：P0=left, P1=(cx, top-40), P2=right
        x = (1 - t) ** 2 * left + 2 * (1 - t) * t * cx + t ** 2 * right
        y = (1 - t) ** 2 * (cy - 10) + 2 * (1 - t) * t * (top - 30) + t ** 2 * (cy - 10)
        upper_pts.append((x, y))

    # 下弧（控制点在下方）
    lower_pts = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * right + 2 * (1 - t) * t * cx + t ** 2 * left
        y = (1 - t) ** 2 * (cy + 10) + 2 * (1 - t) * t * (bottom + 30) + t ** 2 * (cy + 10)
        lower_pts.append((x, y))

    # 旋转所有点
    eye_pts = [rotate(x, y) for x, y in upper_pts + lower_pts]

    # 画眼睛外框
    draw.polygon(eye_pts, fill=NV_GREEN, outline=NV_GREEN)

    # ========== 2. 漩涡纹理（3 条弧线） ==========
    for k in range(3):
        scale = 1.0 - k * 0.25
        arc_pts = []
        for i in range(steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * (cx - 80 * scale) + 2 * (1 - t) * t * cx + t ** 2 * (cx + 80 * scale)
            y = (1 - t) ** 2 * (cy - 5) + 2 * (1 - t) * t * (cy - 20 * scale) + t ** 2 * (cy - 5)
            arc_pts.append(rotate(x, y))
        draw.line(arc_pts, fill=NV_GREEN_DARK, width=3)

    # ========== 3. 中心瞳孔 ==========
    pupil_r = 30
    pupil_x, pupil_y = rotate(cx, cy)
    draw.ellipse(
        [pupil_x - pupil_r, pupil_y - pupil_r, pupil_x + pupil_r, pupil_y + pupil_r],
        fill=NV_GREEN_DARK
    )

    # ========== 4. 下方盾牌 ==========
    shield_top = cy + 130
    shield_w, shield_h = 70, 90
    shield_pts = [
        (cx - shield_w, shield_top),
        (cx + shield_w, shield_top),
        (cx + shield_w, shield_top + shield_h * 0.6),
        (cx, shield_top + shield_h),
        (cx - shield_w, shield_top + shield_h * 0.6),
    ]
    draw.polygon(shield_pts, fill=NV_GREEN, outline=NV_GREEN_DARK)

    # 盾牌内部的对勾
    check_pts = [
        (cx - 25, shield_top + 40),
        (cx - 5, shield_top + 60),
        (cx + 30, shield_top + 20),
    ]
    draw.line(check_pts, fill=BG, width=8, joint="curve")

    return img


def main():
    img = draw_icon()
    png_path = ROOT / "icon.png"
    ico_path = ROOT / "icon.ico"
    img.save(png_path, "PNG")
    img.save(ico_path, "ICO",
             sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"[OK] {png_path}")
    print(f"[OK] {ico_path}")


if __name__ == "__main__":
    main()