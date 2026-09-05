#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

DO_UPDATE=false
DO_PACKAGES=false
DO_OVERCLOCK=false
DO_ENV=false

print_help() {
	cat <<EOF
${SCRIPT_NAME} — Raspberry Pi / Docker host setup

No flags provided, or --help/-h passed. Available flags:

  --update        Run system update/upgrade/autoremove/clean (apt full-upgrade)
  --packages      Install Docker + prerequisites, add repo, add user to groups
                  (docker, dialout, uucp, audio)
  --overclock     Apply dynamic overclock settings for Raspberry Pi 4/5
                  (skipped automatically on non-Pi hardware, or if you already
                  have custom overclock settings in config.txt)
  --env           Generate the docker-compose .env file (UID/GID, audio/serial
                  GIDs, radio device autodetect)
  --all           Run everything above, in order: update, packages, overclock, env
  -h, --help      Show this help message
EOF
}

# ------------------------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------------------------

if [ "$#" -eq 0 ]; then
	print_help
	exit 0
fi

for arg in "$@"; do
	case "$arg" in
		--update)
			DO_UPDATE=true
			;;
		--packages)
			DO_PACKAGES=true
			;;
		--overclock)
			DO_OVERCLOCK=true
			;;
		--env)
			DO_ENV=true
			;;
		--all)
			DO_UPDATE=true
			DO_PACKAGES=true
			DO_OVERCLOCK=true
			DO_ENV=true
			;;
		-h|--help)
			print_help
			exit 0
			;;
		*)
			echo "Unknown flag: $arg"
			echo
			print_help
			exit 1
			;;
	esac
done

# ------------------------------------------------------------------------------
# Section: System update
# ------------------------------------------------------------------------------

run_update() {
	echo "=== Starting System Updates ==="
	sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y && sudo apt clean
}

# ------------------------------------------------------------------------------
# Section: Docker + packages + groups
# ------------------------------------------------------------------------------

run_packages() {
	echo "=== Installing Docker Prerequisites ==="
	sudo apt install -y ca-certificates curl

	echo "=== Adding Docker's Official GPG Key ==="
	sudo install -m 0755 -d /etc/apt/keyrings
	sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
	sudo chmod a+r /etc/apt/keyrings/docker.asc

	echo "=== Adding Repository to Apt Sources ==="
	sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

	sudo apt update

	echo "=== Installing Docker Packages ==="
	sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin git kitty-terminfo

	echo "=== Configuring User Groups ==="
	sudo groupadd -f docker
	sudo usermod -aG docker,dialout,uucp,audio "$USER"
}

# ------------------------------------------------------------------------------
# Section: Overclocking
# ------------------------------------------------------------------------------

run_overclock() {
	echo "=== Applying Dynamic Overclocking ==="

	local config_file="/boot/firmware/config.txt"

	if [ -f /proc/device-tree/model ]; then
		local model_str
		model_str=$(tr -d '\0' < /proc/device-tree/model)

		if grep -Eq "^\s*(arm_freq|over_voltage|over_voltage_delta|gpu_freq)" "$config_file"; then
			echo "Notice: Existing overclock settings detected."
			echo "Skipping dynamic overclocking to preserve your custom configuration."
		else
			case "$model_str" in
				*"Raspberry Pi 4"*)
					echo "Detected: $model_str"
					echo "Appending Pi 4 overclock parameters..."
					sudo tee -a "$config_file" <<EOF

# Raspberry Pi 4 Overclock Settings
over_voltage=6
arm_freq=2000
gpu_freq=750
EOF
					;;
				*"Raspberry Pi 5"*)
					echo "Detected: $model_str"
					echo "Appending Pi 5 overclock parameters..."
					sudo tee -a "$config_file" <<EOF

# Raspberry Pi 5 Overclock Settings
over_voltage_delta=30000
arm_freq=2800
gpu_freq=1000
EOF
					;;
				*)
					echo "Warning: Unknown Pi model ($model_str). Skipping overclock."
					;;
			esac
		fi
	else
		echo "Non-Raspberry Pi system detected — skipping overclocking."
	fi
}

# ------------------------------------------------------------------------------
# Section: docker-compose .env generation
# ------------------------------------------------------------------------------

run_env() {
	echo "=== Generating docker-compose .env file ==="

	local user_uid user_gid audio_gid serial_gid radio_device detected_dev

	user_uid=$(id -u)
	user_gid=$(id -g)

	audio_gid=$(getent group audio | cut -d: -f3 || true)
	audio_gid=${audio_gid:-995}

	serial_gid=$(getent group uucp | cut -d: -f3 || true)
	if [ -z "${serial_gid}" ]; then
		serial_gid=$(getent group dialout | cut -d: -f3 || true)
	fi
	serial_gid=${serial_gid:-984}

	radio_device="/dev/null"
	if [ -d "/dev/serial/by-id" ]; then
		detected_dev=$(find /dev/serial/by-id/ -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1 || true)
		if [ -n "${detected_dev}" ]; then
			radio_device="${detected_dev}"
		fi
	fi

	cat <<EOF | tee .env
# Auto-generated Docker Compose Environment Configuration
UID=${user_uid}
GID=${user_gid}
AUDIO_GID=${audio_gid}
SERIAL_GID=${serial_gid}
RADIO_MODEL=3085
RADIO_DEVICE=${radio_device}
EOF

	echo "=== .env file successfully created ==="
}

# ------------------------------------------------------------------------------
# Run selected sections, in a fixed sensible order regardless of flag order
# ------------------------------------------------------------------------------

if [ "$DO_UPDATE" = true ]; then
	run_update
fi

if [ "$DO_PACKAGES" = true ]; then
	run_packages
fi

if [ "$DO_OVERCLOCK" = true ]; then
	run_overclock
fi

if [ "$DO_ENV" = true ]; then
	run_env
fi

echo "=== Setup Complete ==="
if [ "$DO_PACKAGES" = true ] || [ "$DO_OVERCLOCK" = true ]; then
	echo "Please reboot using 'sudo reboot' to apply changes."
fi
