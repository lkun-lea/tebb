package dev.tebb.mobile

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/** 同一层级切换手机工作区。待答引用沿用主聊的问题版本，主动修改须由已授权电脑接收。 */
@Composable
internal fun MobileWorkspace(state: ChatUiState, owner: String, paired: Boolean, back: () -> Unit,
                            reply: (QuestionKey, String) -> Unit, select: (QuestionKey) -> Unit,
                            connect: () -> Unit) {
    val tabs = listOf("今日", "事项", "日程", "笔记", "知识库", "自动化")
    var page by rememberSaveable { mutableStateOf("今日") }
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
                ScrollableTabRow(tabs.indexOf(page), backgroundColor = Color(0xFFF0F6FA), contentColor = ink,
                    edgePadding = 4.dp) {
                    tabs.forEach { label -> Tab(selected = page == label, onClick = { page = label }, text = { Text(label) }) }
                }
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
