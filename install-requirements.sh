#!/bin/bash
set -e

echo "=== 1. Starting System Updates ==="
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y && sudo apt clean

echo "=== 2. Installing Docker Prerequisites ==="
sudo apt install -y ca-certificates curl

echo "=== 3. Adding Docker's Official GPG Key ==="
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "=== 4. Adding Repository to Apt Sources ==="
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update

echo "=== 5. Installing Docker Packages ==="
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin git kitty-terminfo

echo "=== 6. Configuring User Groups ==="
# Creates group if it doesn't exist, adds the user running the script
sudo groupadd -f docker
sudo usermod -aG docker "$USER"

echo "=== 7. Applying Dynamic Overclocking ==="
CONFIG_FILE="/boot/firmware/config.txt"

# Read the file and clean up missing trailing newlines
MODEL_STR=$(tr -d '\0' < /proc/device-tree/model)

# Safeguard: Check if the file already contains an active 'arm_freq' configuration
if grep -q "^[[:space:]]*arm_freq" "$CONFIG_FILE"; then
        echo "Notice: Existing 'arm_freq' setting detected in $CONFIG_FILE."
        echo "Skipping dynamic overclocking to preserve your custom settings."
else
        if echo "$MODEL_STR" | grep -q "Raspberry Pi 4"; then
                echo "Detected: $MODEL_STR"
                echo "Appending Pi 4 overclock parameters..."
                sudo tee -a "$CONFIG_FILE" <<EOF

# Raspberry Pi 4 Overclock Settings
over_voltage=6 # Voltage boost (default is 0)
arm_freq=2000 # CPU to 2.0 GHz (default is 1.5 GHz)
gpu_freq=750 # GPU to 750 MHz (default is 500 MHz)
EOF

        elif echo "$MODEL_STR" | grep -q "Raspberry Pi 5"; then
                echo "Detected: $MODEL_STR"
                echo "Appending Pi 5 overclock parameters..."
                sudo tee -a "$CONFIG_FILE" <<EOF

# Raspberry Pi 5 Overclock Settings
over_voltage_delta=50000 # Adds ~0.05V to support higher frequencies
arm_freq=3000 # CPU to 3.0 GHz (default is 2.4 GHz)
gpu_freq=1000 # GPU to 1.0 GHz (default ~910 MHz)
EOF

        else
                echo "Warning: Did not explicitly detect a Pi 4 or Pi 5 ($MODEL_STR). Skipping overclock."
        fi
fi

echo "=== Setup Complete ==="
echo "Please reboot using 'sudo reboot' to apply changes."
