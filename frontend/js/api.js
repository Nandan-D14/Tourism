// API Service
const API_BASE = window.location.protocol === 'file:'
    ? 'http://127.0.0.1:8000'
    : window.location.origin;

async function fetchItinerary(requestData) {
    try {
        const response = await fetch(`${API_BASE}/find-places`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestData)
        });
        
        if (!response.ok) {
            const errBase = await response.json().catch(() => ({}));
            const detail = errBase?.detail;
            let message = 'Service unavailable. Please try again.';

            if (typeof detail === 'string' && detail.trim()) {
                message = detail;
            } else if (Array.isArray(detail) && detail.length > 0) {
                const parts = detail.map((item) => {
                    if (item && typeof item === 'object') {
                        const field = Array.isArray(item.loc) ? item.loc.join('.') : 'request';
                        const msg = item.msg || JSON.stringify(item);
                        return `${field}: ${msg}`;
                    }
                    return String(item);
                });
                message = parts.join(' | ');
            } else if (detail && typeof detail === 'object') {
                message = JSON.stringify(detail);
            }

            throw new Error(message);
        }

        return await response.json();
    } catch (err) {
        throw err;
    }
}
