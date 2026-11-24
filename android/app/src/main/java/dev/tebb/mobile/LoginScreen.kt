package dev.tebb.mobile

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** 登录完成后恢复用户刚才选择的入口。首次启动登录成功时直接显示主聊。 */
internal enum class LoginDestination { Cloud, Computer }

/**
 * 使用已有邮箱账号登录。发送验证码和校验共用 [authenticate]，由 [state] 展示真实回执。
 * 点跳过或返回时通过 [skip] 进入本地聊天；请求处理中等待当前回执，避免迟到的登录切换身份。
 */
@Composable
internal fun LoginScreen(state: PairingState, authenticate: (String, String) -> Unit, skip: () -> Unit) {
    var email by rememberSaveable { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    val busy = state == PairingState.Connecting
    BackHandler { if (!busy) skip() }
    MaterialTheme(colors = darkColors(primary = Color(0xFFBDCEA9), background = Color(0xFF151617))) {
        Surface(color = MaterialTheme.colors.background, contentColor = Color.White) {
            Column(Modifier.fillMaxSize().imePadding()
                .verticalScroll(rememberScrollState()).padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally) {
                Column(Modifier.widthIn(max = 440.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    TextButton(skip, Modifier.align(Alignment.End), enabled = !busy) { Text("跳过登录") }
                    Text("tebb.", color = Color.White, fontSize = 36.sp, fontWeight = FontWeight.Bold)
                    Text("登录 tebb", color = Color.White, fontSize = 28.sp)
                    Text("使用与 Windows 相同的账号，继续云聊或连接电脑。", color = Color.LightGray)
                    OutlinedTextField(email, { email = it; code = "" }, Modifier.fillMaxWidth(), enabled = !busy,
                        singleLine = true, label = { Text("邮箱") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                        textStyle = androidx.compose.ui.text.TextStyle(color = Color.White, fontSize = 16.sp))
                    TextButton({ authenticate(email, "") }, enabled = !busy && email.isNotBlank()) { Text("获取验证码") }
                    OutlinedTextField(code, { code = it }, Modifier.fillMaxWidth(), enabled = !busy,
                        singleLine = true, label = { Text("邮箱验证码") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        textStyle = androidx.compose.ui.text.TextStyle(color = Color.White, fontSize = 16.sp))
                    (state as? PairingState.Notice)?.let { Text(it.message, color = Color.LightGray) }
                    Button({ authenticate(email, code) }, Modifier.fillMaxWidth().heightIn(min = 48.dp),
                        enabled = !busy && email.isNotBlank() && code.isNotBlank()) {
                        Text(if (busy) "正在验证…" else "登录")
                    }
                }
            }
        }
    }
}
