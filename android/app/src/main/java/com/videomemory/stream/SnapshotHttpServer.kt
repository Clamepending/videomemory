package com.videomemory.stream

import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.nio.charset.StandardCharsets
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class SnapshotHttpServer(
    private val port: Int,
    private val snapshotProvider: () -> ByteArray?,
) {
    @Volatile
    private var running = false

    private var serverSocket: ServerSocket? = null
    private var acceptThread: Thread? = null
    private val clientExecutor: ExecutorService = Executors.newCachedThreadPool()

    fun start() {
        if (running) return
        val socket = ServerSocket(port).apply {
            reuseAddress = true
        }
        serverSocket = socket
        running = true
        acceptThread = Thread {
            acceptLoop(socket)
        }.apply {
            name = "snapshot-http-accept"
            isDaemon = true
            start()
        }
    }

    fun stop() {
        running = false
        try {
            serverSocket?.close()
        } catch (_: Exception) {
        }
        serverSocket = null
        acceptThread = null
        clientExecutor.shutdownNow()
    }

    private fun acceptLoop(socket: ServerSocket) {
        while (running) {
            try {
                val client = socket.accept()
                clientExecutor.execute { handleClient(client) }
            } catch (e: SocketException) {
                if (running) {
                    Log.w(TAG, "Snapshot server socket error", e)
                }
                break
            } catch (e: Exception) {
                if (running) {
                    Log.w(TAG, "Snapshot server accept failed", e)
                }
            }
        }
    }

    private fun handleClient(socket: Socket) {
        socket.use { client ->
            client.soTimeout = 2000
            try {
                val reader = BufferedReader(InputStreamReader(client.getInputStream(), StandardCharsets.US_ASCII))
                val requestLine = reader.readLine().orEmpty()
                while (reader.readLine()?.isNotEmpty() == true) {
                    // Consume headers.
                }
                val parts = requestLine.split(' ')
                val method = parts.getOrNull(0).orEmpty()
                val path = parts.getOrNull(1).orEmpty().substringBefore('?')
                when {
                    method !in setOf("GET", "HEAD") -> {
                        writeTextResponse(client, 405, "Method Not Allowed", "Only GET and HEAD are supported.\n")
                    }
                    path == "/" -> {
                        writeTextResponse(client, 200, "OK", "VideoMemory snapshot server\nGET /snapshot.jpg\n")
                    }
                    path == "/snapshot.jpg" -> {
                        val snapshot = snapshotProvider()
                        if (snapshot == null) {
                            writeTextResponse(client, 503, "Service Unavailable", "Snapshot not ready yet.\n")
                        } else {
                            writeBinaryResponse(client, 200, "OK", "image/jpeg", snapshot, method == "HEAD")
                        }
                    }
                    else -> {
                        writeTextResponse(client, 404, "Not Found", "Not found.\n")
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Snapshot server request failed", e)
            }
        }
    }

    private fun writeTextResponse(socket: Socket, code: Int, status: String, body: String) {
        writeBinaryResponse(
            socket = socket,
            code = code,
            status = status,
            contentType = "text/plain; charset=utf-8",
            body = body.toByteArray(StandardCharsets.UTF_8),
            headOnly = false,
        )
    }

    private fun writeBinaryResponse(
        socket: Socket,
        code: Int,
        status: String,
        contentType: String,
        body: ByteArray,
        headOnly: Boolean,
    ) {
        val output = socket.getOutputStream()
        val headers = buildString {
            append("HTTP/1.1 $code $status\r\n")
            append("Content-Type: $contentType\r\n")
            append("Content-Length: ${body.size}\r\n")
            append("Cache-Control: no-store, no-cache, must-revalidate\r\n")
            append("Pragma: no-cache\r\n")
            append("Connection: close\r\n")
            append("\r\n")
        }.toByteArray(StandardCharsets.US_ASCII)
        output.write(headers)
        if (!headOnly) {
            output.write(body)
        }
        output.flush()
    }

    companion object {
        private const val TAG = "SnapshotHttpServer"
    }
}
