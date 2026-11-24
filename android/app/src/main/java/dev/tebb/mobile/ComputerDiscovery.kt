package dev.tebb.mobile

import android.util.Base64
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.NetworkInterface
import java.net.SocketTimeoutException
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** 在当前网段广播随机挑战，仅接收能用同账号密钥加密且匹配本轮挑战的邀请。 */
internal fun discoverComputers(owner: String): List<JSONObject> {
    val key = MobileAccount.lease(owner)
    val nonce = UUID.randomUUID().toString().replace("-", "")
    val proof = MobileAccount.proof(key, "discover:$nonce")
    val probe = "tebb2 $nonce $proof".toByteArray()
    val results = mutableMapOf<String, JSONObject>()
    DatagramSocket().use { socket ->
        socket.broadcast = true
        socket.soTimeout = 450
        val targets = NetworkInterface.getNetworkInterfaces().toList().filter { it.isUp && !it.isLoopback }
            .flatMap { it.interfaceAddresses }.mapNotNull { it.broadcast }.distinct()
        check(targets.isNotEmpty()) { "未找到局域网接口，请连接 Wi-Fi" }
        repeat(3) {
            targets.forEach { socket.send(DatagramPacket(probe, probe.size, it, 41926)) }
            val deadline = android.os.SystemClock.elapsedRealtime() + 900
            while (android.os.SystemClock.elapsedRealtime() < deadline) {
                val packet = DatagramPacket(ByteArray(2048), 2048)
                try { socket.receive(packet) } catch (_: SocketTimeoutException) { break }
                val invite = runCatching {
                    val data = Base64.decode(packet.data.copyOf(packet.length), Base64.DEFAULT)
                    require(data.size >= 28)
                    val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                    cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, data, 0, 12))
                    cipher.updateAAD(nonce.toByteArray())
                    JSONObject(String(cipher.doFinal(data, 12, data.size - 12), Charsets.UTF_8))
                }.getOrNull() ?: continue
                if (invite.optString("host") == packet.address.hostAddress) results[invite.optString("pin")] = invite
            }
        }
    }
    return results.values.toList()
}
