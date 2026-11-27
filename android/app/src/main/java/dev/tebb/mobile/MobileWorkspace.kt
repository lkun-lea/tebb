package dev.tebb.mobile

import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.border
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.draw.clip
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/** 在聊天和工作区之间切换；低频目的地集中在「更多」，返回后沿用原会话草稿。 */
@Composable
internal fun WorkspaceNavigation(current: String, enabled: Boolean = true, choose: (String) -> Unit) {
    val destinations = listOf("主聊", "今日", "事项", "更多")
    val selected = if (current in destinations) current else "更多"
    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp)
        .glassSurface(30.dp).padding(5.dp)) {
        destinations.forEachIndexed { index, page ->
            val active = page == selected
            Column(Modifier.weight(1f).heightIn(min = 48.dp)
                .background(if (active) MaterialTheme.colors.primary.copy(alpha = .17f) else Color.Transparent, RoundedCornerShape(24.dp))
                .selectable(active, enabled = enabled, role = Role.Tab, onClick = { choose(page) }),
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Icon(listOf(Icons.Default.Email, Icons.Default.DateRange, Icons.Default.Check, Icons.Default.MoreVert)[index],
                    null, Modifier.size(20.dp))
                Text(if (page == "主聊") "聊天" else page, style = MaterialTheme.typography.caption)
            }
        }
    }
}

internal val LocalNightSky = staticCompositionLocalOf { false }

/** 按设备当地时间切换聊天和工作区的昼夜色彩，前台跨时段时同步刷新。 */
@Composable
internal fun WorkspaceTheme(content: @Composable () -> Unit) {
    fun isNight() = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY) !in 6..17
    val night by produceState(isNight()) {
        while (true) {
            value = isNight()
            kotlinx.coroutines.delay(30_000)
        }
    }
    val palette = if (night) darkColors(primary = Color(0xFF95D5FF), surface = Color(0xFF303954),
        background = Color(0xFF040519), onSurface = Color(0xFFEDF5FF))
    else lightColors(primary = Color(0xFF12678A), onPrimary = Color.White, background = Color(0xFFFAFBF9),
        surface = Color.White, onSurface = Color(0xFF1E3444))
    CompositionLocalProvider(LocalNightSky provides night, LocalContentColor provides palette.onSurface) {
        MaterialTheme(colors = palette, content = content)
    }
}

@Composable
internal fun skyBrush() = Brush.verticalGradient(if (LocalNightSky.current)
    listOf(Color(0xFF040519), Color(0xFF1B1D34), Color(0xFF272B48), Color(0xFF2E3D5C))
    else listOf(Color(0xFFB8D9EF), Color(0xFFE4E7ED), Color(0xFFFAEADC)))

/** 以半透明渐变和细描边绘制玻璃表面，文字和操作保持清晰。 */
@Composable
internal fun Modifier.glassSurface(radius: androidx.compose.ui.unit.Dp): Modifier {
    val shape = RoundedCornerShape(radius)
    val night = LocalNightSky.current
    val colors = if (night) listOf(Color(0xBB43476A), Color(0xC1272F51))
        else listOf(Color(0xCCFFFFFF), Color(0xAEF9FBFE))
    return clip(shape).background(Brush.linearGradient(colors))
        .border(1.dp, Color.White.copy(alpha = if (night) .15f else .65f), shape)
}

/** 同一层级切换手机工作区。待答引用沿用主聊的问题版本，主动修改须由已授权电脑接收。 */
@Composable
internal fun MobileWorkspace(page: String, choose: (String) -> Unit, state: ChatUiState, owner: String, paired: Boolean, back: () -> Unit,
                            reply: (QuestionKey, String) -> Unit, select: (QuestionKey) -> Unit,
                            connect: () -> Unit) {
    var action by rememberSaveable { mutableStateOf("") }
    val secondary = page in listOf("日程", "笔记", "知识库", "自动化")
    BackHandler {
        when {
            action.isNotEmpty() -> action = ""
            secondary -> choose("更多")
            else -> back()
        }
    }
    val paper = skyBrush()
    Column(Modifier.fillMaxSize().background(paper)) {
        Box(Modifier.weight(1f)) {
            if (action.isNotEmpty()) Box(Modifier.fillMaxSize().background(paper)) {
                WorkspaceEntry(action, owner, state.historySnapshot, returnLabel = "返回$page") { action = "" }
            } else Column(Modifier.fillMaxSize().background(paper)) {

                if (page == "今日") JournalScreen(state, paired, back, reply)
                else Column(Modifier.verticalScroll(rememberScrollState()).padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (secondary) TextButton({ choose("更多") }) { Text("返回更多") }
                    Text(page, style = MaterialTheme.typography.h4)
                    Box(Modifier.glassSurface(22.dp)) {
                        Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            if (page == "更多") {
                                listOf("日程", "笔记", "知识库", "自动化").forEach { target ->
                                    DropdownMenuItem(onClick = { choose(target) }) { Text(target) }
                                }
                                TextButton(connect) { Text("我的电脑") }
                            } else if (!paired) Button(connect) { Text("连接我的电脑") }
                            else {
                                if (page == "事项") {
                                    val questions = state.composer.pending.filter { it.deviceId.isNotEmpty() }
                                    if (questions.isEmpty()) Text("当前没有来自电脑的待答事项")
                                    questions.forEach { q -> OutlinedButton({ select(q.key); back() }) { Text(q.prompt) } }
                                }
                                val prompt = when (page) {
                                    "日程" -> "让伙伴安排日程"
                                    "笔记" -> "让伙伴整理笔记"
                                    "知识库" -> "让伙伴处理资料"
                                    "自动化" -> "让伙伴处理自动化"
                                    else -> "让伙伴跟进事项"
                                }
                                Button({ action = "agent.request" }) { Text(prompt) }
                                if (page == "日程") OutlinedButton({ action = "calendar.create" }) { Text("手动安排或修改日程") }
                                if (page == "笔记") OutlinedButton({ action = "note.create" }) { Text("手动新增笔记") }
                            }
                        }
                    }
                }
            }
        }
        if (action.isEmpty()) WorkspaceNavigation(page) { if (it == "主聊") back() else choose(it) }
    }
}
