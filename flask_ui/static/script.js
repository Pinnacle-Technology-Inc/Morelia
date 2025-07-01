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
