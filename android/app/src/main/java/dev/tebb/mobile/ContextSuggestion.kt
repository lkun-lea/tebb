package dev.tebb.mobile

import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

/** 从同一原会话挑出近期仍有效的依据；不同会话即使同名也各自保留。时间单位为秒。 */
internal fun suggestionSources(rows: List<PendingQuestion>, now: Long, hidden: Set<String>): List<PendingQuestion> {
    val eligible = rows.filter { it.deviceId.isNotEmpty() && it.conversation.isNotEmpty() &&
        now - it.created in 0L..7L * 86400 && suggestionId(it) !in hidden }.sortedByDescending { it.created }
    val latest = eligible.firstOrNull() ?: return emptyList()
    return eligible.filter { it.deviceId == latest.deviceId && it.conversation == latest.conversation }
}

internal fun suggestionId(row: PendingQuestion) = listOf(row.deviceId, row.conversation, row.key.runId, row.key.version).joinToString("/")

/** 授权后从获准待答快照生成观察。跳过与纠正只影响推荐，点选原任务才改变输入目标。 */
@Composable
internal fun ContextSuggestion(owner: String, rows: List<PendingQuestion>, select: (QuestionKey) -> Unit) {
    val device = rows.firstOrNull { it.deviceId.isNotEmpty() }?.deviceId ?: return
    val context = LocalContext.current
    val prefs = remember(owner, device) { context.getSharedPreferences("context_suggestion_${owner}_$device", Context.MODE_PRIVATE) }
    var allowed by remember(prefs) { mutableStateOf(prefs.getBoolean("allowed", false)) }
    var dismissed by remember(prefs) { mutableStateOf(prefs.getBoolean("dismissed", false)) }
    var hidden by remember(prefs) { mutableStateOf(prefs.getStringSet("hidden", emptySet()).orEmpty().toSet()) }
    var details by remember(prefs) { mutableStateOf(false) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis() / 1000) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis() / 1000; kotlinx.coroutines.delay(60_000) } }
    val sources = suggestionSources(rows, now, hidden)
    val first = sources.firstOrNull() ?: return
    if (dismissed) return
    fun hide() {
        hidden = hidden + sources.map(::suggestionId)
        prefs.edit().putStringSet("hidden", hidden).apply()
        details = false
    }
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
        if (!allowed) {
            Row {
                TextButton(onClick = { allowed = true; prefs.edit().putBoolean("allowed", true).apply() }) { Text("用电脑待答记录推荐下一步") }
                TextButton(onClick = { dismissed = true; prefs.edit().putBoolean("dismissed", true).apply() }) { Text("跳过") }
            }
        } else {
            Text("待你继续 · " + first.title, color = androidx.compose.ui.graphics.Color.White)
            Row {
                TextButton(onClick = { select(first.key) }) { Text("回复原任务") }
                TextButton(onClick = { details = true }) { Text("查看依据") }
                TextButton(onClick = { hide() }) { Text("跳过") }
            }
        }
    }
    if (details) AlertDialog(onDismissRequest = { details = false }, title = { Text("Windows 原任务") },
        text = { Column(Modifier.verticalScroll(rememberScrollState())) { sources.forEach { row ->
            Text(row.title + "\n" + row.prompt)
            TextButton(onClick = { select(row.key); details = false }) { Text("引用这个问题") }
        } } },
        confirmButton = { TextButton(onClick = { details = false }) { Text("关闭") } },
        dismissButton = { TextButton(onClick = { hide() }) { Text("这不是当前工作") } })
}

