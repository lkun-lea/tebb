package dev.tebb.mobile

import android.content.ContentResolver
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.Column
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import com.google.zxing.BinaryBitmap
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 从系统选择器提供的图片中读取二维码，先按尺寸采样以限制大图的解码内存。 */
private fun readQr(resolver: ContentResolver, uri: Uri): String {
    val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }
    while (maxOf(options.outWidth, options.outHeight) / options.inSampleSize.coerceAtLeast(1) > 1800)
        options.inSampleSize = options.inSampleSize.coerceAtLeast(1) * 2
    options.inJustDecodeBounds = false
    val image = resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }
        ?: error("无法读取二维码图片")
    try {
        val pixels = IntArray(image.width * image.height)
        image.getPixels(pixels, 0, image.width, 0, 0, image.width, image.height)
        val source = RGBLuminanceSource(image.width, image.height, pixels)
        return QRCodeReader().decode(BinaryBitmap(HybridBinarizer(source))).text
    } finally {
        image.recycle()
    }
}

/**
 * 展示 [PairingViewModel] 发布的状态，并把相机或选图得到的二维码交给同一个申请入口。
 * 临时的图片读取错误属于当前界面，网络重试和申请回执由 ViewModel 管理。
 */
@Composable
internal fun PairingPanel(model: PairingViewModel, onDecode: (Boolean) -> Unit) {
    val state by model.state.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var imageError by remember { mutableStateOf(false) }
    val camera = rememberLauncherForActivityResult(ScanContract()) { result ->
        result.contents?.let { model.scanned(it) }
    }
    val image = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) scope.launch {
            onDecode(true)
            try { model.scanned(withContext(Dispatchers.IO) { readQr(context.contentResolver, uri) }) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { imageError = true }
            finally { onDecode(false) }
        }
    }

    val owner by model.signedIn.collectAsState()
    val nearby by model.computers.collectAsState()
    Column(Modifier.verticalScroll(rememberScrollState())) {
        if (owner.isEmpty()) {
            var email by remember { mutableStateOf("") }
            var code by remember { mutableStateOf("") }
            Text("登录与 Windows 相同的 tebb 账号")
            androidx.compose.material.OutlinedTextField(email, { email = it }, label = { Text("邮箱") }, singleLine = true)
            androidx.compose.material.OutlinedTextField(code, { code = it }, label = { Text("邮箱验证码") }, singleLine = true)
            val busy = state == PairingState.Connecting
            TextButton(enabled = !busy && email.isNotBlank(), onClick = { model.authenticate(email, "") }) { Text("获取验证码") }
            TextButton(enabled = !busy && code.isNotBlank() && email.isNotBlank(), onClick = { model.authenticate(email, code) }) { Text("登录") }
            (state as? PairingState.Notice)?.let { Text(it.message) }
        } else {
            TextButton(onClick = model::signOut) { Text("退出账号") }
            when (val current = state) {
                PairingState.Connecting -> Text("正在验证电脑并提交申请…")
                is PairingState.Pending -> Text("请在 ${current.computer} 核对并确认：${current.code}")
                is PairingState.Paired -> {
                    Text("已配对 · ${current.computer}")
                    TextButton(onClick = model::forgetLocal) { Text("移除本机配对记录") }
                }
                else -> {
                    if (current is PairingState.Notice) {
                        Text(current.message)
                        if (current.canRetry) TextButton(onClick = model::retry) { Text("重试连接") }
                    }
                    nearby.forEach { computer ->
                        TextButton(onClick = { model.scanned(computer.toString()) }) { Text(computer.getString("computer")) }
                    }
                    TextButton(onClick = model::discover) { Text("刷新附近电脑") }
                    TextButton(onClick = {
                        imageError = false
                        camera.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                            .setPrompt("扫描 Windows 上的 tebb 配对码").setBeepEnabled(false))
                    }) { Text("扫码配对 Windows") }
                    TextButton(onClick = { imageError = false; image.launch("image/*") }) { Text("从图片识别配对码") }
                    if (imageError) Text("图片中未识别到配对二维码")
                }
            }
        }
    }
}
