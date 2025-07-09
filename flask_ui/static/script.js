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
    <td><input type="file" name="config_file_new[]" /></td>
    <td>
      <select name="device_type[]">
      	<option value="None">--Select--</option>
        <option value="Pod8206HR">Pod8206HR</option>
        <option value="Pod8229">Pod8229</option>
        <option value="Pod8274D">Pod8274D</option>
        <option value="Pod8401HR">Pod8401HR</option>
        <option value="Pod8480SC">Pod8480SC</option>
      </select>
    </td>
    <td><input type="text" name="device_port[]" value="/dev/ttyUSB${rowCount}" /></td>
    <td><input type="text" name="placeholder1[]" value="placeholder" /></td>
    <td><input type="checkbox" name="PH2_${rowCount}" value="true" /></td>
    <td><input type="checkbox" name="PH3_${rowCount}" value="true" /></td>
    <td><input type="number" name="placeholder4[]" value="1000" /></td>
    <td><button type="button" onclick="deleteRow(this)">&#128465;</button></td>
  `;

  tbody.appendChild(row);  
}


