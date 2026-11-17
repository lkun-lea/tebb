//! 桌宠窗口位置约束：以窗口底部居中的形象区域为锚点，保证它始终留在显示器工作区内。
//! 拖动增量、惯性滑行和重新显示都经过这里，避免窗口被推出屏幕后无法找回。
use std::sync::{Mutex, MutexGuard};
use tauri::{PhysicalPosition, WebviewWindow};

/// 桌宠锚点的逻辑尺寸，与内置形象支持的最大尺寸一致。
const ANCHOR_SIZE: f64 = 64.0;
/// 锚点底边与窗口底边的逻辑间距，与内置形象距窗口底 20 像素的定位一致。
const ANCHOR_BOTTOM_GAP: f64 = 20.0;
/// 锚点与工作区边缘保留的逻辑边距，保证边缘处仍可拖动。
const EDGE_MARGIN: f64 = 8.0;
/// 找回桌宠时窗口与工作区右下角保留的逻辑间距。
const RECOVER_MARGIN: f64 = 24.0;

#[derive(Clone, Copy, Debug, PartialEq)]
struct Area {
    x: i32,
    y: i32,
    w: i32,
    h: i32,
}

impl Area {
    /// 判定锚点中心是否仍在缓存工作区内；贴边继续推时会重新解析目标工作区。
    fn contains(&self, point: (i64, i64)) -> bool {
        point.0 >= self.x as i64
            && point.0 <= (self.x + self.w) as i64
            && point.1 >= self.y as i64
            && point.1 <= (self.y + self.h) as i64
    }
}

#[derive(Clone, Copy, Debug)]
struct Frame {
    x: i32,
    y: i32,
    w: u32,
    h: u32,
    scale: f64,
}

impl Frame {
    fn read(window: &WebviewWindow) -> Result<Self, String> {
        let position = window.outer_position().map_err(|err| err.to_string())?;
        let size = window.outer_size().map_err(|err| err.to_string())?;
        let scale = window.scale_factor().map_err(|err| err.to_string())?;
        Ok(Self { x: position.x, y: position.y, w: size.width, h: size.height, scale })
    }

    /// 锚点中心在虚拟桌面中的物理坐标。
    fn anchor_center(&self) -> (i64, i64) {
        let (offset_x, offset_y) = anchor_center_offset(self);
        (self.x as i64 + offset_x as i64, self.y as i64 + offset_y as i64)
    }
}

/// 约束目标：离锚点最近的显示器工作区及其缩放比例。
#[derive(Clone, Copy, Debug)]
struct Target {
    area: Area,
    scale: f64,
}

/// 拖动期间的窗口几何缓存。
/// 热路径只更新这份状态，不再每帧经 IPC 读取窗口并枚举显示器，避免移动滞后。
#[derive(Default)]
pub struct Tracker(Mutex<Option<State>>);

#[derive(Clone, Copy, Debug)]
struct State {
    frame: Frame,
    area: Area,
}

impl Tracker {
    fn lock(&self) -> Result<MutexGuard<'_, Option<State>>, String> {
        self.0.lock().map_err(|err| err.to_string())
    }
}

/// 逻辑像素换算成物理像素。
fn px(logical: f64, scale: f64) -> i32 {
    (logical * scale).round() as i32
}

/// 锚点在窗口内的左上角偏移和物理尺寸。
fn anchor_geometry(frame: &Frame) -> (i32, i32, i32) {
    let size = px(ANCHOR_SIZE, frame.scale).max(1);
    let gap = px(ANCHOR_BOTTOM_GAP, frame.scale);
    (frame.w as i32 / 2 - size / 2, frame.h as i32 - gap - size, size)
}

/// 锚点中心相对窗口左上角的物理偏移。
fn anchor_center_offset(frame: &Frame) -> (i32, i32) {
    let (offset_x, offset_y, size) = anchor_geometry(frame);
    (offset_x + size / 2, offset_y + size / 2)
}

/// 校正窗口左上角，使桌宠锚点中心落在工作区内并保留拖动边距。
/// 只约束中心而不是整个锚点矩形，跨相邻显示器时不会被强行推开。
fn constrain(frame: &Frame, desired: (i32, i32), area: Area) -> (i32, i32) {
    let (offset_x, offset_y) = anchor_center_offset(frame);
    let margin = px(EDGE_MARGIN, frame.scale).max(1);
    let min_x = area.x + margin;
    let max_x = (area.x + area.w - margin).max(min_x);
    let min_y = area.y + margin;
    let max_y = (area.y + area.h - margin).max(min_y);
    let x = (desired.0 + offset_x).clamp(min_x, max_x) - offset_x;
    let y = (desired.1 + offset_y).clamp(min_y, max_y) - offset_y;
    (x, y)
}

/// 锚点到工作区的距离平方；落在工作区内为 0。
fn distance_squared(area: Area, point: (i64, i64)) -> i64 {
    let dx = if point.0 < area.x as i64 {
        area.x as i64 - point.0
    } else if point.0 > (area.x + area.w) as i64 {
        point.0 - (area.x + area.w) as i64
    } else {
        0
    };
    let dy = if point.1 < area.y as i64 {
        area.y as i64 - point.1
    } else if point.1 > (area.y + area.h) as i64 {
        point.1 - (area.y + area.h) as i64
    } else {
        0
    };
    dx * dx + dy * dy
}

/// 窗口跨到另一块显示器后逻辑尺寸不变，按目标缩放换算物理尺寸。
fn project(frame: &Frame, scale: f64) -> Frame {
    if (scale - frame.scale).abs() < f64::EPSILON {
        return *frame;
    }
    Frame {
        x: frame.x,
        y: frame.y,
        w: (frame.w as f64 / frame.scale * scale).round() as u32,
        h: (frame.h as f64 / frame.scale * scale).round() as u32,
        scale,
    }
}

/// 选择离桌宠锚点最近的工作区，跨显示器和拼接缝隙时都收敛到最近的一块。
fn target_at(window: &WebviewWindow, point: (i64, i64)) -> Result<Target, String> {
    let mut nearest: Option<(i64, Target)> = None;
    for monitor in window.available_monitors().map_err(|err| err.to_string())? {
        let work = monitor.work_area();
        let area = Area {
            x: work.position.x,
            y: work.position.y,
            w: work.size.width as i32,
            h: work.size.height as i32,
        };
        let distance = distance_squared(area, point);
        if nearest.map_or(true, |(best, _)| distance < best) {
            nearest = Some((distance, Target { area, scale: monitor.scale_factor() }));
        }
    }
    nearest
        .map(|(_, target)| target)
        .ok_or_else(|| "找不到可用的显示器，暂时无法定位桌宠。".to_string())
}

/// 读取窗口实际几何，并按当前锚点确定工作区。
fn read_state(window: &WebviewWindow) -> Result<State, String> {
    let frame = Frame::read(window)?;
    let target = target_at(window, frame.anchor_center())?;
    Ok(State { frame, area: target.area })
}

/// 按目标缩放投影窗口，并让锚点中心落在期望位置；返回校正后的窗口几何。
fn positioned_frame(frame: &Frame, center: (i64, i64), target: Target) -> Frame {
    let projected = project(frame, target.scale);
    let (offset_x, offset_y) = anchor_center_offset(&projected);
    let desired = (center.0 as i32 - offset_x, center.1 as i32 - offset_y);
    let (x, y) = constrain(&projected, desired, target.area);
    Frame { x, y, w: projected.w, h: projected.h, scale: projected.scale }
}

/// 按下开始拖动时刷新基准位置；之后移动都以这份状态为基准，不会因读取滞后丢增量。
pub fn refresh(window: &WebviewWindow, tracker: &Tracker) -> Result<(), String> {
    let state = read_state(window)?;
    *tracker.lock()? = Some(state);
    Ok(())
}

/// 按逻辑像素移动桌宠，移动后立即约束回工作区，惯性滑行同样受此限制。
pub fn move_by(window: &WebviewWindow, tracker: &Tracker, dx: f64, dy: f64) -> Result<(), String> {
    let mut guard = tracker.lock()?;
    if guard.is_none() {
        *guard = Some(read_state(window)?);
    }
    let state = guard.as_mut().ok_or("桌宠位置状态初始化失败。")?;
    let anchor = state.frame.anchor_center();
    let center = (
        anchor.0 + (dx * state.frame.scale).round() as i64,
        anchor.1 + (dy * state.frame.scale).round() as i64,
    );
    // 目标锚点仍在当前工作区时直接复用缓存，避免每帧枚举显示器。
    let target = if state.area.contains(center) {
        Target { area: state.area, scale: state.frame.scale }
    } else {
        target_at(window, center)?
    };
    let next = positioned_frame(&state.frame, center, target);
    if (next.x, next.y) != (state.frame.x, state.frame.y) {
        window.set_position(PhysicalPosition::new(next.x, next.y)).map_err(|err| err.to_string())?;
    }
    *state = State { frame: next, area: target.area };
    Ok(())
}

/// 只在当前位置越出工作区时校正，供隐藏后重新显示使用。
pub fn ensure_visible(window: &WebviewWindow, tracker: &Tracker) -> Result<(), String> {
    let frame = Frame::read(window)?;
    let center = frame.anchor_center();
    let target = target_at(window, center)?;
    let next = positioned_frame(&frame, center, target);
    if (next.x, next.y) != (frame.x, frame.y) {
        window.set_position(PhysicalPosition::new(next.x, next.y)).map_err(|err| err.to_string())?;
    }
    *tracker.lock()? = Some(State { frame: next, area: target.area });
    Ok(())
}

/// 把桌宠移回当前显示器右下角，作为屏幕外时的找回入口。
pub fn recover(window: &WebviewWindow, tracker: &Tracker) -> Result<(), String> {
    let frame = Frame::read(window)?;
    let target = target_at(window, frame.anchor_center())?;
    let projected = project(&frame, target.scale);
    let margin = px(RECOVER_MARGIN, projected.scale).max(1);
    let desired = (
        target.area.x + target.area.w - projected.w as i32 - margin,
        target.area.y + target.area.h - projected.h as i32 - margin,
    );
    let (x, y) = constrain(&projected, desired, target.area);
    window.set_position(PhysicalPosition::new(x, y)).map_err(|err| err.to_string())?;
    let next = Frame { x, y, w: projected.w, h: projected.h, scale: projected.scale };
    *tracker.lock()? = Some(State { frame: next, area: target.area });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        anchor_center_offset, constrain, distance_squared, positioned_frame, project, Area, Frame,
        Target,
    };

    fn frame(scale: f64) -> Frame {
        // 与 tauri.conf.json 中桌宠窗口的 260x380 逻辑尺寸一致。
        Frame { x: 0, y: 0, w: (260.0 * scale) as u32, h: (380.0 * scale) as u32, scale }
    }

    #[test]
    fn stays_put_while_inside_the_work_area() {
        let desktop = Area { x: 0, y: 0, w: 1920, h: 1080 };
        assert_eq!(constrain(&frame(1.0), (100, 500), desktop), (100, 500));
    }

    #[test]
    fn clamps_anchor_center_to_left_top_and_right_bottom_edges() {
        let desktop = Area { x: 0, y: 0, w: 1920, h: 1080 };
        // 锚点中心在窗口内偏移 (130, 328)，边缘保留 8 像素。
        assert_eq!(constrain(&frame(1.0), (-500, -500), desktop), (-122, -320));
        assert_eq!(constrain(&frame(1.0), (2000, 2000), desktop), (1782, 744));
    }

    #[test]
    fn clamps_on_scaled_and_negative_coordinate_monitors() {
        let left = Area { x: -1920, y: 0, w: 1920, h: 1080 };
        assert_eq!(constrain(&frame(1.0), (-3000, 100), left), (-2042, 100));
        // 150% 缩放下窗口为 390x570，锚点中心偏移 (195, 492)，边距 12 像素。
        let high_dpi = Area { x: 0, y: 0, w: 2880, h: 1620 };
        assert_eq!(constrain(&frame(1.5), (5000, 5000), high_dpi), (2673, 1116));
    }

    #[test]
    fn tiny_work_area_keeps_the_anchor_center_at_the_start_edge() {
        let small = Area { x: 0, y: 0, w: 40, h: 40 };
        assert_eq!(constrain(&frame(1.0), (100, 100), small), (-98, -296));
    }

    #[test]
    fn measures_distance_to_nearest_work_area() {
        let desktop = Area { x: 0, y: 0, w: 1920, h: 1080 };
        assert_eq!(distance_squared(desktop, (100, 100)), 0);
        assert_eq!(distance_squared(desktop, (1923, 1084)), 25);
        assert_eq!(distance_squared(desktop, (-3, 1084)), 25);
        assert!(desktop.contains((100, 100)));
        assert!(!desktop.contains((1921, 100)));
    }

    #[test]
    fn keeps_logical_size_when_target_monitor_uses_another_scale() {
        let projected = project(&frame(1.0), 1.5);
        assert_eq!((projected.w, projected.h, projected.scale), (390, 570, 1.5));
        let unchanged = project(&frame(1.25), 1.25);
        assert_eq!((unchanged.w, unchanged.h), ((260.0_f64 * 1.25) as u32, (380.0_f64 * 1.25) as u32));
    }

    #[test]
    fn keeps_anchor_center_when_moving_to_another_scale() {
        let current = Frame { x: 100, y: 500, w: 260, h: 380, scale: 1.0 };
        let area = Area { x: 0, y: 0, w: 1920, h: 1080 };
        let next = positioned_frame(&current, current.anchor_center(), Target { area, scale: 1.5 });
        let (offset_x, offset_y) = anchor_center_offset(&next);
        assert_eq!((next.x + offset_x, next.y + offset_y), (230, 828));
        assert_eq!((next.w, next.h), (390, 570));
    }
}
