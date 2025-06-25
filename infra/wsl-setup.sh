# Ubuntu (WSL) set up

# Ensure Bash is installed
#if ! command -v bash >/dev/null 2>&1; then
#    echo "bash is not installed. Installing it now..."
#    sudo apt update && sudo apt install -y bash
#fi

echo "Starting Ubuntu setup program..."

windows_confirm="unconfirmed"

shopt -s nocasematch
while [[ $windows_confirm != "confirm" ]]; do
   read -p "Return to Windows Terminal and finish Windows Setup. Type confirm when finished: " windows_confirm
done
shopt -u nocasematch

after=($(ls /dev/ttyUSB* 2>/dev/null))

# Find entries in $after that weren't in $before
new_nodes=()
for dev in "${after[@]}"; do
  found=0
  for old in "${before[@]}"; do
    [[ "$dev" == "$old" ]] && { found=1; break; }
  done
  [[ $found -eq 0 ]] && new_nodes+=("$dev")
done

if [[ ${#new_nodes[@]} -eq 0 ]]; then
  echo "No new /dev/ttyUSB devices detected."
else
  echo "New device node(s): ${new_nodes[*]}"
  # Store the first new path into a variable for further use
  new_path=${new_nodes[0]}
  # You can now use $new_path in your logic
fi

# Give the new /dev/ttyUSB devices permission
if [[ ${#new_nodes[@]} -eq 0 ]]; then
    echo "Nothing to chmod – no new /dev/ttyUSB* devices."
else
    for device_path in "${new_nodes[@]}"; do
        echo "Changing permissions for: $device_path"
        sudo chmod 666 "$device_path"
    done
fi

echo "Ubuntu setup complete!"

# Run the live demo !!
chmod +x live_demo.py
python3 live_demo.py "${new_nodes[@]}"

