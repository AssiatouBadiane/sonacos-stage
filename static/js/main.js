// SONACOS — main.js

// Mascot bubble toggle
function toggleMascotBubble() {
  const bubble = document.getElementById('mascotBubble');
  if (bubble) bubble.classList.toggle('show');
}

// Auto-close mascot bubble after 5s on load
document.addEventListener('DOMContentLoaded', () => {
  const bubble = document.getElementById('mascotBubble');
  if (bubble) {
    setTimeout(() => bubble.classList.add('show'), 1500);
    setTimeout(() => bubble.classList.remove('show'), 6500);
  }

  // Close bubble when clicking outside
  document.addEventListener('click', (e) => {
    const container = document.getElementById('mascotContainer');
    if (container && !container.contains(e.target)) {
      if (bubble) bubble.classList.remove('show');
    }
  });

  // Global search
  const gSearch = document.getElementById('globalSearch');
  if (gSearch) {
    gSearch.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && gSearch.value.trim()) {
        window.location.href = `/manuels?search=${encodeURIComponent(gSearch.value.trim())}`;
      }
    });
  }

  // Auto-dismiss flash messages
  document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => el.remove(), 5000);
  });
});
