package dev.tebb.mobile

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

@Composable
internal fun WorkspaceMenu(current: String, enabled: Boolean = true, choose: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        TextButton(onClick = { expanded = true }, enabled = enabled) { Text("☰  $current") }
        if (expanded) Dialog(onDismissRequest = { expanded = false },
            properties = DialogProperties(usePlatformDefaultWidth = false)) {
            BoxWithConstraints(Modifier.fillMaxSize()) {
                Spacer(Modifier.fillMaxSize().clickable { expanded = false })
                Surface(modifier = Modifier.width(maxWidth.coerceAtMost(294.dp)).fillMaxHeight(),
                    color = Color(0xFFFAFBF9), contentColor = Color(0xFF1E3444),
                    shape = RoundedCornerShape(topEnd = 20.dp, bottomEnd = 20.dp)) {
                    Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically) {
                            Text("tebb.", style = MaterialTheme.typography.h5)
                            TextButton(onClick = { expanded = false }) { Text("关闭") }
                        }
                        listOf("主聊", "今日", "事项", "日程", "笔记", "知识库", "自动化").forEach { page ->
                            DropdownMenuItem(onClick = { expanded = false; choose(page) },
                                modifier = Modifier.background(if (page == current) Color(0xFFD2E5ED) else Color.Transparent,
                                    RoundedCornerShape(12.dp))) {
                                Text(if (page == current) "✓  $page" else page)
                            }
                        }
                    }
                }
            }
        }
    }
}

/** 同一层级切换手机工作区。待答引用沿用主聊的问题版本，主动修改须由已授权电脑接收。 */
@Composable
internal fun MobileWorkspace(page: String, choose: (String) -> Unit, state: ChatUiState, owner: String, paired: Boolean, back: () -> Unit,
                            reply: (QuestionKey, String) -> Unit, select: (QuestionKey) -> Unit,
                            connect: () -> Unit) {
    var action by rememberSaveable { mutableStateOf("") }
    val ink = Color(0xFF182D40)
    val accent = Color(0xFF0075AD)
    BackHandler { if (action.isEmpty()) back() else action = "" }
    val paper = Brush.verticalGradient(listOf(Color(0xFFC3DCF0), Color(0xFFE8EDF5), Color(0xFFF6E5D4)))
    MaterialTheme(colors = lightColors(primary = accent, onSurface = ink)) {
        Surface(color = Color.Transparent, contentColor = ink) {
            if (action.isNotEmpty()) Box(Modifier.fillMaxSize().background(paper)) {
                WorkspaceEntry(action, owner, state.historySnapshot, returnLabel = "返回$page") { action = "" }
            } else Column(Modifier.fillMaxSize().background(paper)) {
                WorkspaceMenu(page) { if (it == "主聊") back() else choose(it) }
                if (page == "今日") JournalScreen(state, paired, back, reply)
                else Column(Modifier.verticalScroll(rememberScrollState()).padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    TextButton(back) { Text("返回主聊") }
                    Text(page, style = MaterialTheme.typography.h4)
                    Card(shape = RoundedCornerShape(24.dp), backgroundColor = Color.White.copy(alpha = .86f)) {
                        Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            if (!paired) Button(connect) { Text("连接我的电脑") }
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
    }
}
