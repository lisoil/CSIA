async function updateSlots(region, action) {
    const response = await fetch(`/slots/${region}/${action}`, {
        method: 'POST'
    });
    const data = await response.json();
    document.getElementById(`region${region}-slots-left`).textContent = data.slots_left;
}

async function refreshSlots(region) {
    const response = await fetch(`/slots/${region}/get`);
    const data = await response.json();
    document.getElementById(`region${region}-slots-left`).textContent = data.slots_left;
}

// Refresh every 5 minutes
setInterval(() => {
    refreshSlots(1);
    refreshSlots(2);
}, 300000); // 5 minutes

// Initial refresh on page load
refreshSlots(1);
refreshSlots(2);

// Auto-refresh page for certifier every 1 min
if (window.is_certifier) {
    setInterval(() => {
        window.location.reload();
    }, 60000);
}
