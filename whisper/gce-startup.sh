#!/bin/bash
# Startup script for the Whisper GPU VM (Compute Engine, image family common-cu129-ubuntu-2204-nvidia-580: NVIDIA driver
# installed, no Docker). Runs on every boot. First boot builds a Python venv with the same pins as the Dockerfile and
# downloads the model (a few minutes, kept on the disk); every boot then runs server.py and powers the VM off when it
# exits (it exits by itself after IDLE_EXIT_SECONDS without a request), so a stopped VM only costs its disk.
# Metadata keys: whisper-server (server.py contents, required), whisper-idle (seconds, default 300).
set -u
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
mkdir -p /opt/whisper
curl -sf -H "Metadata-Flavor: Google" $MD/whisper-server -o /opt/whisper/server.py
IDLE=$(curl -sf -H "Metadata-Flavor: Google" $MD/whisper-idle || echo 300)
cat > /usr/local/bin/whisper-run.sh <<EOF
#!/bin/bash
# output also goes to the serial console: gcloud compute instances get-serial-port-output <vm> | grep whisper-run
set -u
log() { echo "whisper-run: \$* \$(date -u +%FT%TZ)" | tee -a /var/log/whisper-run.log > /dev/ttyS0; }
V=/opt/whisper/venv
if [ ! -x \$V/bin/python ] || [ ! -f /opt/whisper/models/large-v3-turbo/model.bin ]; then
  log "setup"
  python3 -m venv \$V || { apt-get update -q && apt-get install -yq python3-venv && python3 -m venv \$V; }
  \$V/bin/pip install -q "faster-whisper==1.2.1" "ctranslate2==4.6.0" "nvidia-cublas-cu12==12.4.5.8" "nvidia-cudnn-cu12==9.1.0.70" \
    && \$V/bin/python -c "from faster_whisper import download_model; download_model('large-v3-turbo', output_dir='/opt/whisper/models/large-v3-turbo')" \
    || { log "setup failed"; sleep 600; /usr/bin/systemctl poweroff; exit 1; }
  log "setup done"
fi
SP=\$(\$V/bin/python -c "import site; print(site.getsitepackages()[0])")
export LD_LIBRARY_PATH=\$SP/nvidia/cublas/lib:\$SP/nvidia/cudnn/lib
export WHISPER_MODEL_DIR=/opt/whisper/models/large-v3-turbo WHISPER_DEVICE=cuda WHISPER_COMPUTE=float16 IDLE_EXIT_SECONDS=$IDLE PORT=8080
log "server start"
\$V/bin/python /opt/whisper/server.py 2>&1 | tee -a /var/log/whisper-server.log | grep --line-buffered -E '"event": "(model_loaded|idle_exit|error)"' > /dev/ttyS0
rc=\${PIPESTATUS[0]}
log "server exited rc=\$rc"
# rc 0 = idle exit: power off now. Anything else: leave 10 minutes to look, then power off anyway.
[ "\$rc" = 0 ] || sleep 600
/usr/bin/systemctl poweroff
EOF
chmod +x /usr/local/bin/whisper-run.sh
cat > /etc/systemd/system/whisper.service <<'EOF'
[Unit]
Description=Whisper server (powers the VM off when it exits)
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=/usr/local/bin/whisper-run.sh
Restart=no
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl restart whisper.service
