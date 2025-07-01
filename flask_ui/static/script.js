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

// Load Config button logic
  /*document.getElementById('load_config').addEventListener('click', () => {
    document.getElementById('file_input').click();
  });

  document.getElementById('file_input').addEventListener('change', async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    if (!file.name.endsWith('.toml')) {
      alert('Please upload a .toml file');
      return;
    }

    const text = await file.text();

    try {
      const parsed = TOML.parse(text);

      // Fill form fields manually:
      document.getElementById('filename').value = parsed.filename || '';

      document.getElementById('channel_1').value = parsed.channel_names?.channel_1 || '';
      document.getElementById('channel_2').value = parsed.channel_names?.channel_2 || '';
      document.getElementById('channel_3').value = parsed.channel_names?.channel_3 || '';

      document.getElementById('sample_rate').value = parsed.information?.sample_rate || '400';
      document.getElementById('preamp_gain').value = parsed.information?.preamp_gain || '100';

      document.getElementById('eeg1').value = parsed.channel_settings?.eeg1 || '';
      document.getElementById('eeg2').value = parsed.channel_settings?.eeg2 || '';
      document.getElementById('emg').value = parsed.channel_settings?.emg || '';
      document.getElementById('notch_value').value = parsed.channel_settings?.notch_value || '';
      document.getElementById('notch_enabled').checked = parsed.channel_settings?.notch_enabled === 'true';

      // TTL1
      document.getElementById('ttl1_output').checked = parsed.ttl_controls?.ttl1?.output === 'true';
      document.getElementById('ttl1_set_state').checked = parsed.ttl_controls?.ttl1?.set_state === 'true';
      document.getElementById('ttl1_set_current_state').checked = parsed.ttl_controls?.ttl1?.current_state === 'true';
      document.getElementById('ttl1_rising_event').checked = parsed.ttl_controls?.ttl1?.rising_event === 'true';
      document.getElementById('ttl1_falling_event').checked = parsed.ttl_controls?.ttl1?.falling_event === 'true';
      document.getElementById('ttl1_event_comment').value = parsed.ttl_controls?.ttl1?.event_comment || '';

      // TTL2
      document.getElementById('ttl2_output').checked = parsed.ttl_controls?.ttl2?.output === 'true';
      document.getElementById('ttl2_set_state').checked = parsed.ttl_controls?.ttl2?.set_state === 'true';
      document.getElementById('ttl2_set_current_state').checked = parsed.ttl_controls?.ttl2?.current_state === 'true';
      document.getElementById('ttl2_rising_event').checked = parsed.ttl_controls?.ttl2?.rising_event === 'true';
      document.getElementById('ttl2_falling_event').checked = parsed.ttl_controls?.ttl2?.falling_event === 'true';
      document.getElementById('ttl2_event_comment').value = parsed.ttl_controls?.ttl2?.event_comment || '';

      // TTL3
      document.getElementById('ttl3_output').checked = parsed.ttl_controls?.ttl3?.output === 'true';
      document.getElementById('ttl3_set_state').checked = parsed.ttl_controls?.ttl3?.set_state === 'true';
      document.getElementById('ttl3_set_current_state').checked = parsed
      */
