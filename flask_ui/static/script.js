/*
function sayHello() {
    alert("Hello from JavaScript!");
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('deviceForm');

  form.addEventListener('submit', function (e) {
    e.preventDefault();

    const formData = new FormData(this);
    const username = formData.get('username');

    console.log('Username:', username);

    fetch('/submit', {
      method: 'POST',
      body: formData
    }).then(response => response.text())
      .then(data => {
        console.log('Server responded: ', data);
        alert(data);
      });
  });
})
*/
