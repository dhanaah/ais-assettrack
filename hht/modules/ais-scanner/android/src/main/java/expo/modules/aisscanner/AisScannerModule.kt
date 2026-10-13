// AIS AssetTrack - hardware scanner input without a keyboard. The device scanner (Zebra DataWedge, Urovo, Newland,
// iData, Chainway, ...) sends each barcode as an Android broadcast; this module receives it and passes it to the app.
// No text field, no keystrokes, no keyboard. Zebra DataWedge is configured automatically (own profile for the app).
// Developed by DT
package expo.modules.aisscanner

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Bundle
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import androidx.core.content.ContextCompat
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class AisScannerModule : Module() {
  private var receiver: BroadcastReceiver? = null
  private var keys: List<String> = emptyList()

  private val ctx: Context?
    get() = appContext.reactContext?.applicationContext

  override fun definition() = ModuleDefinition {
    Name("AisScanner")
    Events("onScan")

    Function("manufacturer") { "${Build.MANUFACTURER} ${Build.MODEL}" }

    // Listen to the scanner broadcasts: actions to accept and the extra keys that carry the barcode text
    Function("start") { actions: List<String>, dataKeys: List<String> ->
      stopReceiver()
      val c = ctx ?: return@Function false
      keys = dataKeys
      val r = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
          if (intent == null) return
          var data: String? = null
          for (k in keys) {
            val v = intent.extras?.get(k) ?: continue
            data = when (v) {
              is String -> v
              is ByteArray -> String(v, Charsets.UTF_8)
              else -> v.toString()
            }
            if (!data.isNullOrBlank()) break
          }
          if (data.isNullOrBlank()) return
          val type = intent.getStringExtra("com.symbol.datawedge.label_type") ?: intent.getStringExtra("barcodeType") ?: ""
          sendEvent("onScan", mapOf("data" to data.trim(), "type" to type, "action" to (intent.action ?: "")))
        }
      }
      val f = IntentFilter()
      actions.forEach { f.addAction(it) }
      f.addCategory(Intent.CATEGORY_DEFAULT)
      ContextCompat.registerReceiver(c, r, f, ContextCompat.RECEIVER_EXPORTED)
      receiver = r
      true
    }

    Function("stop") { stopReceiver() }

    // VPN (customer HHT): is a VPN connection up right now?
    Function("isVpnActive") {
      val c = ctx ?: return@Function false
      try {
        val cm = c.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        cm.allNetworks.any { n -> cm.getNetworkCapabilities(n)?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true }
      } catch (_: Exception) { false }
    }

    // Open the first installed app from the list (e.g. FortiClient VPN). Returns its package, or "" if none installed.
    Function("openApp") { packages: List<String> ->
      val c = ctx ?: return@Function ""
      for (pkg in packages) {
        val i = c.packageManager.getLaunchIntentForPackage(pkg) ?: continue
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try { c.startActivity(i); return@Function pkg } catch (_: Exception) {}
      }
      ""
    }

    // Zebra DataWedge: own profile for this app - barcode input on, broadcast output on, keystroke output OFF
    Function("configureZebra") { profile: String, action: String ->
      val c = ctx ?: return@Function false
      val pkg = c.packageName
      fun send(extraKey: String, value: Any) {
        val i = Intent().setAction("com.symbol.datawedge.api.ACTION")
        when (value) {
          is String -> i.putExtra(extraKey, value)
          is Bundle -> i.putExtra(extraKey, value)
        }
        c.sendBroadcast(i)
      }
      send("com.symbol.datawedge.api.CREATE_PROFILE", profile)
      fun cfg(plugin: Bundle, withApp: Boolean): Bundle {
        val b = Bundle()
        b.putString("PROFILE_NAME", profile)
        b.putString("PROFILE_ENABLED", "true")
        b.putString("CONFIG_MODE", "UPDATE")
        if (withApp) {
          val app = Bundle()
          app.putString("PACKAGE_NAME", pkg)
          app.putStringArray("ACTIVITY_LIST", arrayOf("*"))
          b.putParcelableArray("APP_LIST", arrayOf(app))
        }
        b.putBundle("PLUGIN_CONFIG", plugin)
        return b
      }
      fun plugin(name: String, params: Map<String, String>): Bundle {
        val p = Bundle(); p.putString("PLUGIN_NAME", name); p.putString("RESET_CONFIG", "true")
        val pl = Bundle(); params.forEach { (k, v) -> pl.putString(k, v) }
        p.putBundle("PARAM_LIST", pl)
        return p
      }
      send("com.symbol.datawedge.api.SET_CONFIG", cfg(plugin("BARCODE", mapOf("scanner_selection" to "auto", "scanner_input_enabled" to "true",
        "decoder_qrcode" to "true", "decoder_datamatrix" to "true", "decoder_code128" to "true", "decoder_code39" to "true")), true))
      send("com.symbol.datawedge.api.SET_CONFIG", cfg(plugin("INTENT", mapOf("intent_output_enabled" to "true",
        "intent_action" to action, "intent_category" to Intent.CATEGORY_DEFAULT, "intent_delivery" to "2")), false))
      send("com.symbol.datawedge.api.SET_CONFIG", cfg(plugin("KEYSTROKE", mapOf("keystroke_output_enabled" to "false")), false))
      true
    }

    OnDestroy { stopReceiver() }
  }

  private fun stopReceiver() {
    val c = ctx
    receiver?.let { r -> try { c?.unregisterReceiver(r) } catch (_: Exception) {} }
    receiver = null
  }
}
