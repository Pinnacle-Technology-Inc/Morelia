// Side Device Navigation
document.addEventListener("DOMContentLoaded", function () {
  const selector = document.getElementById("device_type");
  if (selector) {
    selector.addEventListener("change", function () {
      const selectedValue = this.value;
      if (selectedValue) {
        window.location.href = selectedValue;
      }
    });
  }
});


// Cancel (Reset) Buttons
document.addEventListener("DOMContentLoaded", function () {
  window.cancelAndReset = function () {
    const form = document.getElementById("configForm");
    if (form) form.reset();

    const cancelForm = document.getElementById("cancelForm");
    if (cancelForm) {
      cancelForm.submit();
    } else {
      console.error("Cancel form not found in DOM.");
    }
  };
});

// Clear Config File
function clearLoadedConfig() {
  fetch("/clear_config", {
    method: "POST"
  }).then(() => {
    window.location.reload(); // Reload page without session config
  });
}

// Experiment Configuration Functions
// Delete a device row
function deleteRow(btn) {
  const row = btn.closest("tr");
  row.parentNode.removeChild(row);
}

// Remove all devices from the table
function removeAllDevices() {
  const tbody = document.querySelector("#deviceTable tbody");
  tbody.innerHTML = "";
}

// Add a new device row to the table
function addNewDevice() {
  const tbody = document.querySelector("#deviceTable tbody");
  const rowCount = tbody.children.length;
  const row = document.createElement("tr");

  row.innerHTML = `
    <td><input type="text" name="device_name[]" value="Pod_${rowCount + 1}" /></td>
    <td><input type="text" name="device_id[]"/></td>
    <td><input type="file" name="config_file_new[]" class="config-upload" accept=".toml" /></td>
    <td>
      <select name="device_type[]" class="device-type-dropdown">
        <option value="">--Select--</option>
        <option value="Pod8206HR">Pod8206HR</option>
        <option value="Pod8229">Pod8229</option>
        <option value="Pod8274D">Pod8274D</option>
        <option value="Pod8401HR">Pod8401HR</option>
        <option value="Pod8480SC">Pod8480SC</option>
      </select>
    </td>
    <td><input type="text" name="placeholder1[]" value="placeholder" /></td>
    <td><input type="checkbox" name="PH2_${rowCount}" value="true" /></td>
    <td><input type="checkbox" name="PH3_${rowCount}" value="true" /></td>
    <td><input type="number" name="placeholder4[]" value="1000" /></td>
    <td><button type="button" onclick="deleteRow(this)">&#128465;</button></td>
  `;

  tbody.appendChild(row);

  // Also, add the event listener to the new file input so it triggers the device type auto-population
  const newFileInput = row.querySelector(".config-upload");
  if (newFileInput) {
    newFileInput.addEventListener("change", async (event) => {
      const file = event.target.files[0];
      if (!file || !file.name.endsWith(".toml")) return;

      try {
        const text = await file.text();
        const data = simpleTomlParse(text);
        const title = data.title || "";
        let inferredType = title.replace("Device Configuration File", "").trim();

        const dropdown = row.querySelector(".device-type-dropdown");
        if (dropdown) {
          const found = Array.from(dropdown.options).some(opt => opt.value === inferredType);
          if (found) {
            dropdown.value = inferredType;
          } else if (inferredType.length > 0) {
            const newOption = new Option(inferredType, inferredType);
            dropdown.add(newOption);
            dropdown.value = inferredType;
          }
        }
      } catch (err) {
        alert("Failed to read TOML file: " + err.message);
        console.error(err);
      }
    });
  }
}


// Track already-added devices by ID+PORT to avoid duplicates
const detectedDeviceKeys = new Set();

// Need to update the maps to have the correct types
function getDeviceTypeLabel(typeCode) {
  const typeMap = {
    "48": "Pod8206HR",
    "52": "Pod8229",
    "46": "Pod8274D",
    "49": "Pod8401HR",
    "50": "Pod8480SC"
  };
  return typeMap[typeCode] || "Unknown Device";
}

function detectDevices() {
  const tbody = document.querySelector("#deviceTable tbody");
  tbody.innerHTML = ""; // Clear old rows

  const flashBox = document.getElementById("device-flash");
  detectedDeviceKeys.clear(); // Clear old device key tracking

  fetch("/api/devices")
    .then(response => response.json())
    .then(devices => {
      console.log("Detected devices:", devices);

      if (devices.length > 0) {
        const messages = devices.map(d =>
          `${getDeviceTypeLabel(d.TYPE)} (ID: ${d.ID}, Port: ${d.PORT})`
        );
        flashBox.innerText = `Detected Devices:\n${messages.join("\n")}`;
        flashBox.style.display = "block";

        setTimeout(() => {
          flashBox.style.display = "none";
        }, 7000);
      } else {
        flashBox.innerText = "No Pod devices found.";
        flashBox.style.display = "block";
        setTimeout(() => {
          flashBox.style.display = "none";
        }, 5000);
      }

      devices.forEach(device => {
        const key = `${device.ID}_${device.PORT}`;
        if (!detectedDeviceKeys.has(key)) {
          detectedDeviceKeys.add(key);
          addDetectedDeviceRow(device);
        }
      });
    })
    .catch(error => {
      console.error("Device detection failed:", error);
      alert("Failed to detect devices.");
    });
}

function addDetectedDeviceRow(device) {
  const tbody = document.querySelector("#deviceTable tbody");
  const rowCount = tbody.children.length;
  const row = document.createElement("tr");
  const defaultType = getDeviceTypeLabel(device.TYPE);

  row.innerHTML = `
    <td><input type="text" name="device_name[]" value="Pod_${rowCount+1}" /></td>
    <td><input type="text" name="device_id[]" value="${device.ID}" /></td>
    <td><input type="file" name="config_file_new[]" class="config-upload" accept=".toml" /></td>
    <td>
      <select name="device_type[]" class="device-type-dropdown">
        <option value="">--Select--</option>
        <option value="Pod8206HR" ${defaultType === "Pod8206HR" ? "selected" : ""}>Pod8206HR</option>
        <option value="Pod8229" ${defaultType === "Pod8229" ? "selected" : ""}>Pod8229</option>
        <option value="Pod8274D" ${defaultType === "Pod8274D" ? "selected" : ""}>Pod8274D</option>
        <option value="Pod8401HR" ${defaultType === "Pod8401HR" ? "selected" : ""}>Pod8401HR</option>
        <option value="Pod8480SC" ${defaultType === "Pod8480SC" ? "selected" : ""}>Pod8480SC</option>
        ${defaultType === "Unknown Device" ? `<option value="Unknown Device" selected>Unknown Device</option>` : ""}
      </select>
    </td>
    <td><input type="text" name="placeholder1[]" value="placeholder" /></td>
    <td><input type="checkbox" name="PH2_${rowCount}" value="true" /></td>
    <td><input type="checkbox" name="PH3_${rowCount}" value="true" /></td>
    <td><input type="number" name="placeholder4[]" value="1000" /></td>
    <td><button type="button" onclick="deleteRow(this)">&#128465;</button></td>
  `;

  tbody.appendChild(row);

  // Rebind TOML config upload logic
  const fileInput = row.querySelector(".config-upload");
  if (fileInput) {
    fileInput.addEventListener("change", async (event) => {
      const file = event.target.files[0];
      if (!file || !file.name.endsWith(".toml")) return;

      try {
        const text = await file.text();
        const data = simpleTomlParse(text);
        const title = data.title || "";
        const inferredType = title.replace("Device Configuration File", "").trim();

        const dropdown = row.querySelector(".device-type-dropdown");
        if (dropdown) {
          const found = Array.from(dropdown.options).some(opt => opt.value === inferredType);
          if (found) {
            dropdown.value = inferredType;
          } else if (inferredType.length > 0) {
            const newOption = new Option(inferredType, inferredType);
            dropdown.add(newOption);
            dropdown.value = inferredType;
          }
        }
      } catch (err) {
        alert("Failed to read TOML file: " + err.message);
        console.error(err);
      }
    });
  }
}

