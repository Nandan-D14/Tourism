// Map Management
let mapInstance = null;
let markers = [];

function initMap() {
    if (mapInstance) return mapInstance;
    
    mapInstance = L.map('map-container').setView([20, 0], 2);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; CartoDB',
        maxZoom: 19
    }).addTo(mapInstance);
    
    return mapInstance;
}

function renderMap(places) {
    const map = initMap();
    
    // Clear existing markers
    markers.forEach(m => map.removeLayer(m));
    markers = [];
    
    if (!places || places.length === 0) return;

    const bounds = L.latLngBounds();
    
    places.forEach((place, index) => {
        const lat = Number(place?.lat);
        const lng = Number(place?.lng);
        if (Number.isFinite(lat) && Number.isFinite(lng)) {
            const marker = L.marker([lat, lng]).addTo(map);
            const nearby = Array.isArray(place?.nearby_places) && place.nearby_places.length > 0
                ? `<br><span style="color:#666;">Nearby:</span> ${place.nearby_places.slice(0, 2).join(', ')}`
                : '';
            const food = Array.isArray(place?.nearby_restaurants) && place.nearby_restaurants.length > 0
                ? `<br><span style="color:#666;">Food:</span> ${place.nearby_restaurants.slice(0, 2).join(', ')}`
                : '';
            marker.bindPopup(
                `<b>${index + 1}. ${place?.name || 'Place'}</b><br>` +
                `Rating: ${place?.rating || 'N/A'} ⭐${nearby}${food}`
            );
            markers.push(marker);
            bounds.extend([lat, lng]);
        }
    });

    if (markers.length > 0) {
        map.fitBounds(bounds, { padding: [50, 50] });
    }
}
