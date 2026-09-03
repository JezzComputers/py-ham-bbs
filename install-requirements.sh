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
sudo usermod -aG docker,dialout,uucp,audio "$USER"

echo "=== 7. Applying Dynamic Overclocking ==="

CONFIG_FILE="/boot/firmware/config.txt"

if [ -f /proc/device-tree/model ]; then
	MODEL_STR=$(tr -d '\0' < /proc/device-tree/model)

	if grep -Eq "^\s*(arm_freq|over_voltage|over_voltage_delta|gpu_freq)" "$CONFIG_FILE"; then
		echo "Notice: Existing overclock settings detected."
		echo "Skipping dynamic overclocking to preserve your custom configuration."
	else
		case "$MODEL_STR" in
			*"Raspberry Pi 4"*)
				echo "Detected: $MODEL_STR"
				echo "Appending Pi 4 overclock parameters..."
				sudo tee -a "$CONFIG_FILE" <<EOF

# Raspberry Pi 4 Overclock Settings
over_voltage=6
arm_freq=2000
gpu_freq=750
EOF
				;;
			*"Raspberry Pi 5"*)
				echo "Detected: $MODEL_STR"
				echo "Appending Pi 5 overclock parameters..."
				sudo tee -a "$CONFIG_FILE" <<EOF

# Raspberry Pi 5 Overclock Settings
over_voltage_delta=30000
arm_freq=2800
gpu_freq=1000
EOF
				;;
			*)
				echo "Warning: Unknown Pi model ($MODEL_STR). Skipping overclock."
				;;
		esac
	fi
else
	echo "Non-Raspberry Pi system detected — skipping overclocking."
fi

echo "=== 8. Generating docker-compose .env file ==="
printf "UID=%s\nGID=%s\n" "$(id -u)" "$(id -g)" > .env
echo ".env file created with UID=$(id -u) and GID=$(id -g)"

echo "=== Setup Complete ==="
echo "Please reboot using 'sudo reboot' to apply changes."
