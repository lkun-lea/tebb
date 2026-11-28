package dev.tebb.mobile

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.UUID

/** 展示当前配对电脑允许读取的业务记录，离开页面后释放正文。 */
@Composable
internal fun PairedWorkspaceRecords(page: String, owner: String) {
    val context = LocalContext.current
    val action = when (page) {
        "笔记" -> "note.list"
        "知识库" -> "knowledge.list"
        else -> "automation.list"
    }
    val heading = when (page) {
        "笔记" -> "最近编辑"
        "知识库" -> "当前知识库"
        else -> "运行状态"
    }
    val device = PairingClient.approved(context)?.pairedId
    var revision by remember(page) { mutableIntStateOf(0) }
    var rows by remember(page, owner, device) { mutableStateOf(emptyList<JSONObject>()) }
    var selected by remember(page, owner, device) { mutableStateOf<JSONObject?>(null) }
    var status by remember(page, owner, device) { mutableStateOf("") }
    LaunchedEffect(page, owner, device, revision) {
        selected = null
        rows = emptyList()
        status = "正在读取…"
        try {
            val result = withContext(Dispatchers.IO) {
                val client = requireNotNull(PairingClient.approved(context)) { "请重新连接电脑" }
                check(client.pairedId == device && MobileAccount.owner == owner) { "配对已变化" }
                client.create(action, UUID.randomUUID().toString(), JSONObject()).getJSONArray("rows")
            }
            rows = List(result.length()) { result.getJSONObject(it) }
            status = if (rows.isEmpty()) "暂无记录" else ""
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { status = e.message ?: "读取失败" }
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(heading, style = MaterialTheme.typography.caption)
        TextButton({ revision++ }) { Text("刷新") }
    }
    if (status.isNotEmpty()) Text(status)
    rows.filter { it.optString("kind") != "run" }.forEachIndexed { index, row ->
        Column(Modifier.fillMaxWidth().clickable { selected = row }.padding(vertical = 8.dp)) {
            Text(row.getString("title"), style = if (index == 0) MaterialTheme.typography.h6 else MaterialTheme.typography.subtitle1)
            if (page == "自动化") Text(if (row.optBoolean("enabled")) "已启用" else "已暂停")
            val detail = row.optString("detail")
            if (detail.isNotBlank()) Text(detail, maxLines = 2, style = MaterialTheme.typography.body2)
        }
    }
    if (page == "自动化") {
        val history = rows.filter { it.optString("result").isNotEmpty() }.sortedByDescending { it.optString("stamp") }
        if (history.isNotEmpty()) Text("最近运行", style = MaterialTheme.typography.subtitle1)
        history.forEach { row -> Text(listOf(row.optString("stamp"), row.getString("title"), row.optString("result")).filter { it.isNotBlank() }.joinToString(" · ")) }
    }
    selected?.let { row ->
        AlertDialog(onDismissRequest = { selected = null }, title = { Text(row.getString("title")) },
            text = { Text(listOf(row.optString("detail"),row.optString("stamp"),row.optString("result")).filter { it.isNotBlank() }.joinToString("\n")) },
            confirmButton = { TextButton({ selected = null }) { Text("关闭") } })
    }
}
