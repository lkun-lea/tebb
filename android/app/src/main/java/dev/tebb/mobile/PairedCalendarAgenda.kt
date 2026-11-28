package dev.tebb.mobile

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.UUID

/** 电脑只返回这台手机创建的记录，每次打开日程或从编辑返回时重新读取。 */
@Composable
internal fun PairedCalendarAgenda(onEdit: (JSONObject) -> Unit) {
    val context = LocalContext.current
    var revision by remember { mutableIntStateOf(0) }
    var rows by remember { mutableStateOf(emptyList<JSONObject>()) }
    var status by remember { mutableStateOf("") }
    LaunchedEffect(revision) {
        status = "正在读取日程…"
        try {
            val result = withContext(Dispatchers.IO) {
                val client = requireNotNull(PairingClient.approved(context)) { "请重新连接电脑" }
                client.create("calendar.list", UUID.randomUUID().toString(), JSONObject()).getJSONArray("events")
            }
            rows = List(result.length()) { result.getJSONObject(it) }.sortedBy { it.getString("start") }
            status = if (rows.isEmpty()) "还没有通过这台手机新增的日程" else ""
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { rows = emptyList(); status = e.message ?: "读取日程失败" }
    }
    Text("我的日程", style = MaterialTheme.typography.h6)
    if (status.isNotEmpty()) Text(status)
    rows.forEach { event ->
        Column(Modifier.fillMaxWidth().clickable { onEdit(event) }.padding(vertical = 12.dp)) {
            Text(event.getString("summary"), style = MaterialTheme.typography.subtitle1)
            Text(event.getString("start").take(16).replace("T", " ") + " — " +
                event.getString("end").take(16).replace("T", " "), style = MaterialTheme.typography.caption)
        }
    }
    TextButton({ revision++ }) { Text("刷新日程") }
}
