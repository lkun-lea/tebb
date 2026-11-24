package dev.tebb.mobile

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Surface
import androidx.compose.material.Text
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupPositionProvider
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt

/** 使用锚点实际可见的中心定位桌宠。列表回收或滚出可见区域时释放该位置。 */
@Composable
internal fun PetAnchor(size: Dp, moved: (Offset?) -> Unit) {
    val current by rememberUpdatedState(moved)
    DisposableEffect(Unit) { onDispose { current(null) } }
    Spacer(Modifier.size(size).onGloballyPositioned {
        val bounds = it.boundsInRoot()
        current(if (bounds.isEmpty) null else bounds.center)
    })
}

/** 在同一绘制层移动纸白圆点，位置由布局决定，眨眼、呼吸和点按反馈只改变绘制效果。 */
@Composable
internal fun ChatPet(center: Offset, diameter: Dp, waiting: Boolean, listening: Boolean, location: String, pendingCount: Int) {
    val position by animateOffset(center)
    val width by animateDpAsState(diameter, tween(420))
    val touchSize = maxOf(48.dp, width)
    val half = with(LocalDensity.current) { touchSize.toPx() / 2 }
    val cycle = rememberInfiniteTransition()
    val breath by cycle.animateFloat(1f, 1.025f, infiniteRepeatable(tween(1800), RepeatMode.Reverse))
    val eyes by cycle.animateFloat(1f, 1f, infiniteRepeatable(keyframes {
        durationMillis = 4800
        1f at 2000
        .10f at 2090
        1f at 2180
    }))
    val tap = remember { Animatable(1f) }
    var taps by remember { mutableIntStateOf(0) }
    var greeted by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(false) }
    var speech by remember(location) { mutableStateOf<String?>(null) }
    LaunchedEffect(location) {
        if (location == "聊天中央" && !greeted) {
            greeted = true
            speech = "今天想聊点什么？"
        }
    }
    val accessibility = androidx.compose.ui.platform.LocalAccessibilityManager.current
    LaunchedEffect(taps, location, speech) {
        if (speech != null) {
            val timeoutMillis = 5_000L
            delay(accessibility?.calculateRecommendedTimeoutMillis(timeoutMillis, containsText = true) ?: timeoutMillis)
            speech = null
        }
    }
    LaunchedEffect(taps) {
        if (taps > 0) {
            tap.animateTo(.85f, tween(85))
            tap.animateTo(1f, spring(dampingRatio = .38f, stiffness = 520f))
        }
    }
    Box(Modifier.offset { IntOffset((position.x - half).roundToInt(), (position.y - half).roundToInt()) }
        .size(touchSize).semantics { contentDescription = "tebb 桌宠 · $location" }
        .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null,
            role = Role.Button, onClickLabel = "听听 tebb 说什么") {
                speech = petBrief(taps, pendingCount)
                taps++
            }, contentAlignment = Alignment.Center) {
        speech?.let { PetSpeech(it) }
        Canvas(Modifier.size(width).graphicsLayer {
            scaleX = breath * (2f - tap.value)
            scaleY = breath * tap.value
        }) {
            val u = size.width / 64f
            drawCircle(Color(0xFFD4CABA), 29.5f * u)
            drawCircle(Color(0xFFEEE9DC), 28f * u)
            for (right in listOf(false, true)) {
                val short = waiting && right && !listening
                val h = (if (short) 5 else 11) * u * eyes
                val y = if (listening) 36f else if (short) 34f else 31.5f
                drawRoundRect(Color(0xFF3E4443), Offset((if (right) 37f else 22f) * u, y * u - h / 2),
                    Size(5f * u, h), CornerRadius(2.5f * u))
            }
        }
    }
}

/** 将中心点作为整体插值，新消息到达或快速返回时从动画的当前位置继续。 */
@Composable
private fun animateOffset(center: Offset) =
    animateValueAsState(center, Offset.VectorConverter, tween(420, easing = FastOutSlowInEasing))

/** 点击时读取设备日期和当前待答快照。连续点击交替显示日期与待答数量。 */
private fun petBrief(taps: Int, pendingCount: Int): String {
    if (taps % 2 == 0) {
        val today = SimpleDateFormat("M月d日，EEEE", Locale.SIMPLIFIED_CHINESE).format(Date())
        return "今天是${today}。"
    }
    return if (pendingCount == 0) "目前没有等你确认的问题。" else "有 ${pendingCount} 个问题等你确认。"
}

/** 气泡跟随桌宠的实际触摸区域，优先显示在上方，顶栏空间不足时显示在下方。 */
@Composable
private fun PetSpeech(text: String) {
    val margin = with(LocalDensity.current) { 8.dp.roundToPx() }
    val placement = remember(margin) {
        object : PopupPositionProvider {
            override fun calculatePosition(anchorBounds: IntRect, windowSize: IntSize,
                layoutDirection: LayoutDirection, popupContentSize: IntSize): IntOffset {
                val left = anchorBounds.center.x - popupContentSize.width / 2
                val below = anchorBounds.bottom + margin
                val above = anchorBounds.top - margin - popupContentSize.height
                val top = if (above >= margin) above else below
                return IntOffset(left.coerceIn(margin, maxOf(margin, windowSize.width - popupContentSize.width - margin)),
                    top.coerceIn(margin, maxOf(margin, windowSize.height - popupContentSize.height - margin)))
            }
        }
    }
    Popup(popupPositionProvider = placement) {
        Surface(shape = RoundedCornerShape(16.dp), color = Color(0xFFEEE9DC)) {
            Text(text, Modifier.widthIn(max = 260.dp).padding(horizontal = 14.dp, vertical = 9.dp)
                .semantics { liveRegion = LiveRegionMode.Polite }, fontSize = 14.sp, color = Color(0xFF303530))
        }
    }
}
