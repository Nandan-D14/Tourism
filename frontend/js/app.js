const chatFlow = [
    { key: 'city', prompt: 'Great! Where are you dreaming of going? (e.g. Tokyo, Paris, Bali)', type: 'text', placeholder: 'Type destination...' },
    { key: 'dates', prompt: 'When are you planning to travel?', type: 'text', placeholder: 'e.g. Next week, July 10-15...' },
    { key: 'duration_days', prompt: 'How many days will you be travelling?', type: 'quick', options: ['1', '2', '3', '5', '7'], placeholder: 'Type number of days...' },
    { key: 'group_type', prompt: 'Who is tagging along on this adventure?', type: 'quick', options: ['solo', 'couple', 'family', 'friends'], placeholder: 'Select group size...' },
    { key: 'interest', prompt: 'What is the primary focus of this trip?', type: 'quick', options: ['Culture & History', 'Food & Culinary', 'Adventure & Nature', 'Relaxation', 'Nightlife'], placeholder: 'Select or type primary interest...' },
    { key: 'budget', prompt: 'What kind of budget are we looking at?', type: 'quick', options: ['Budget', 'Mid-range', 'Luxury'], placeholder: 'Select or type budget...' },
    { key: 'diet', prompt: 'Any specific dietary preferences?', type: 'quick', options: ['No restrictions', 'Vegetarian', 'Vegan', 'Halal', 'Gluten-free'], placeholder: 'Type any dietary limits...' },
    { key: 'pace', prompt: 'How would you like the pace of your itinerary?', type: 'quick', options: ['Relaxed (1-2 big things/day)', 'Medium (Balanced)', 'Packed (See it all!)'], placeholder: 'Select or type pace...' }
];

let state = {
    step: 0,
    requestData: {}
};

function parseDurationInput(input) {
    const matches = String(input).match(/\d+/g);
    if (!matches || matches.length === 0) return 3;

    const nums = matches.map((n) => parseInt(n, 10)).filter((n) => Number.isFinite(n));
    if (nums.length === 0) return 3;

    // For ranges like "1-3", use the upper bound.
    const raw = String(input);
    const picked = raw.includes('-') || raw.toLowerCase().includes('to')
        ? nums[nums.length - 1]
        : nums[0];

    return Math.max(1, Math.min(10, picked));
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatWeatherContext(weatherContext) {
    if (typeof weatherContext === 'string' && weatherContext.trim()) {
        return weatherContext;
    }
    if (weatherContext && typeof weatherContext === 'object') {
        const condition = weatherContext.condition || weatherContext.summary || weatherContext.weather;
        const temperature = weatherContext.temperature || weatherContext.temp || weatherContext.current_temperature;
        const bestTime = weatherContext.best_time || weatherContext.best_window;
        const parts = [];
        if (condition && temperature) parts.push(`${condition}, around ${temperature}.`);
        else if (condition) parts.push(`${condition}.`);
        else if (temperature) parts.push(`Around ${temperature}.`);
        if (bestTime) parts.push(`Best outing window: ${bestTime}.`);
        return parts.join(' ').trim() || 'Weather details were unavailable for this plan.';
    }
    return 'Weather details were unavailable for this plan.';
}

function normalizeItineraryDays(itineraryValue) {
    const rawDays = Array.isArray(itineraryValue)
        ? itineraryValue
        : (itineraryValue ? [itineraryValue] : []);

    return rawDays.map((day, index) => {
        const slotOrder = ['morning', 'midmorning', 'afternoon', 'evening'];
        const activities = Array.isArray(day?.activities)
            ? day.activities
            : slotOrder
                .map((slot) => {
                    const slotData = day?.[slot];
                    if (!slotData || typeof slotData !== 'object') return null;
                    return {
                        slot,
                        time: slotData.time,
                        place: slotData.place,
                        activity: slotData.activity,
                        travel_note: slotData.travel_note,
                        description: slotData.description,
                    };
                })
                .filter(Boolean);

        return {
            dayLabel: day?.day ? `Day ${day.day}` : `Day ${index + 1}`,
            theme: day?.theme || 'Recommended Flow',
            activities,
        };
    }).filter((day) => Array.isArray(day.activities) && day.activities.length > 0);
}

function findPlaceByName(places, placeName) {
    const needle = String(placeName || '').trim().toLowerCase();
    if (!needle) return null;
    return places.find((place) => {
        const name = String(place?.name || '').trim().toLowerCase();
        return name === needle || needle.includes(name) || name.includes(needle);
    }) || null;
}

document.addEventListener('DOMContentLoaded', () => {
    const chatInput = document.getElementById('chat-input');
    const chatForm = document.getElementById('chat-form');
    const quickReplies = document.getElementById('quick-replies');

    // Handle enter key in textarea
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const msg = chatInput.value.trim();
        if (!msg) return;

        // Add user message
        addUserMessage(msg);
        chatInput.value = '';
        quickReplies.innerHTML = '';
        quickReplies.classList.add('hidden');

        // Process answer
        await handleUserInput(msg);
    });

    chatInput.placeholder = chatFlow[0].placeholder;
    chatInput.focus();
});

function addBotMessage(text) {
    const container = document.getElementById('chat-container');
    const el = document.createElement('div');
    el.className = 'flex items-start gap-4 max-w-4xl mx-auto w-full animate-fade-in translate-y-4 opacity-0 transition-all duration-300 ease-out';
    
    // Auto-fadeIn trick
    setTimeout(() => { el.classList.remove('translate-y-4', 'opacity-0'); }, 50);

    el.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-white flex items-center justify-center flex-shrink-0 mt-1 shadow-md">
            <svg class="w-5 h-5 text-black transform rotate-12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path></svg>
        </div>
        <div class="flex-1 space-y-1">
            <p class="font-semibold text-sm text-gray-300">Wanderlust AI</p>
            <div class="prose prose-invert max-w-none text-brandText leading-relaxed">
                <div class="${text === 'Thinking...' ? 'animate-pulse' : ''}">${text}</div>
            </div>
        </div>
    `;
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
    return el;
}

function addUserMessage(text) {
    const container = document.getElementById('chat-container');
    const el = document.createElement('div');
    el.className = 'flex items-start gap-4 max-w-4xl mx-auto w-full flex-row-reverse animate-fade-in translate-y-4 opacity-0 transition-all duration-300 ease-out';
    
    setTimeout(() => { el.classList.remove('translate-y-4', 'opacity-0'); }, 50);

    el.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-surfaceAlt border border-white/10 flex items-center justify-center flex-shrink-0 mt-1 pb-0.5">
            <span class="text-xs font-bold font-sans">U</span>
        </div>
        <div class="flex-1 flex justify-end">
            <div class="bg-surfaceAlt border border-white/5 px-5 py-3 rounded-2xl rounded-tr-sm text-brandText shadow-sm max-w-[85%] text-left text-sm md:text-base">
                ${text}
            </div>
        </div>
    `;
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
}

function renderQuickReplies(options) {
    const container = document.getElementById('quick-replies');
    container.innerHTML = '';
    options.forEach(opt => {
        const btn = document.createElement('button');
        btn.className = 'px-4 py-2 bg-surfaceAlt hover:bg-white hover:text-black border border-surfaceAlt rounded-full text-sm font-medium text-white transition-all shadow-sm';
        btn.textContent = opt;
        btn.onclick = () => {
            const chatInput = document.getElementById('chat-input');
            chatInput.value = opt;
            document.getElementById('chat-form').dispatchEvent(new Event('submit'));
        };
        container.appendChild(btn);
    });
    container.classList.remove('hidden');
}

async function handleUserInput(msg) {
    if (state.step >= chatFlow.length) {
        state.step = 0;
        state.requestData = {};
    }

    const currentParam = chatFlow[state.step];
    
    // Parse numeric for duration
    let val = msg;
    if (currentParam.key === 'duration_days') val = parseDurationInput(msg);
    
    state.requestData[currentParam.key] = val;
    state.step++;

    if (state.step < chatFlow.length) {
        // Ask next question
        setTimeout(() => {
            const nextParam = chatFlow[state.step];
            addBotMessage(nextParam.prompt);
            document.getElementById('chat-input').placeholder = nextParam.placeholder;
            if (nextParam.type === 'quick') {
                renderQuickReplies(nextParam.options);
            }
        }, 400);
    } else {
        // Finished
        document.getElementById('chat-input').disabled = true;
        document.getElementById('chat-input').placeholder = 'Generating...';
        document.getElementById('chat-send').disabled = true;
        
        const loader = addBotMessage("Amazing. Crafting your perfect itinerary. This might take a few seconds... ✨");

        try {
            const data = await fetchItinerary(state.requestData);
            
            loader.querySelector('.prose').innerHTML = ''; 
            
            // Clone template
            const template = document.getElementById('results-template').cloneNode(true);
            template.id = 'active-results';
            loader.querySelector('.prose').appendChild(template);
            template.classList.remove('hidden');

            renderResultsData(data, state.requestData, template);

            document.getElementById('chat-input').disabled = false;
            document.getElementById('chat-input').placeholder = 'Type another destination to plan a new trip...';
            document.getElementById('chat-send').disabled = false;
            document.getElementById('chat-input').focus();
            state.step = chatFlow.length;

        } catch (err) {
            loader.querySelector('.prose').innerHTML = `<p class="text-red-400">Oops! Failed to plan trip: ${err.message}</p>`;
            document.getElementById('chat-input').disabled = false;
            document.getElementById('chat-input').placeholder = 'Type to retry...';
            document.getElementById('chat-send').disabled = false;
            state.step--; // retry last step
        }
    }
}

function renderResultsData(data, requestData, rootNode) {
    const cityName = data.city || requestData.city;
    const datesStr = requestData.dates ? ` (${requestData.dates})` : '';
    rootNode.querySelector('#result-title').textContent = `${data.duration_days || requestData.duration_days}-Day ${requestData.group_type.charAt(0).toUpperCase() + requestData.group_type.slice(1)} Itinerary for ${cityName}${datesStr}`;

    const chipCity = rootNode.querySelector('#chip-city');
    const chipDates = rootNode.querySelector('#chip-dates');
    const chipBudget = rootNode.querySelector('#chip-budget');
    const chipPace = rootNode.querySelector('#chip-pace');
    const chipDiet = rootNode.querySelector('#chip-diet');
    if (chipCity) chipCity.textContent = cityName || '-';
    if (chipDates) chipDates.textContent = requestData.dates || 'Flexible';
    if (chipBudget) chipBudget.textContent = requestData.budget || 'Mid-range';
    if (chipPace) chipPace.textContent = requestData.pace || 'Medium';
    if (chipDiet) chipDiet.textContent = requestData.diet || 'No restrictions';

    const places = Array.isArray(data.places) ? data.places : [];
    const nearbyStops = places.reduce((sum, place) => {
        const placeCount = Array.isArray(place?.nearby_places) ? place.nearby_places.length : 0;
        const foodCount = Array.isArray(place?.nearby_restaurants) ? place.nearby_restaurants.length : 0;
        return sum + placeCount + foodCount;
    }, 0);

    rootNode.querySelector('#weather-text').textContent = formatWeatherContext(data.weather_context);
    rootNode.querySelector('#events-text').textContent =
        (typeof data.events_context === 'string' && data.events_context.trim())
            ? data.events_context
            : `Planned with ${places.length || 'curated'} main stops and ${nearbyStops || 'additional'} nearby recommendations for smoother exploration.`;

    const timelineEl = rootNode.querySelector('#itinerary-timeline');
    timelineEl.innerHTML = '';
    const normalizedDays = normalizeItineraryDays(data.itinerary);

    normalizedDays.forEach((day, index) => {
        const dayCard = document.createElement('div');
        dayCard.className = 'timeline-track relative bg-surfaceAlt/30 border border-surfaceAlt p-6 rounded-2xl shadow-sm overflow-hidden group';

        let activitiesHtml = '';
        day.activities.forEach((act) => {
                const placeName = act.place || act.place_name || act.name || 'Planned stop';
                const matchedPlace = findPlaceByName(places, placeName);
                const explanation = act.description || act.activity || matchedPlace?.description || 'Explore this stop at a comfortable pace and cover its key highlights.';
                const travelNote = act.travel_note || '';
                const nearbyHint = Array.isArray(matchedPlace?.nearby_restaurants) && matchedPlace.nearby_restaurants.length > 0
                    ? `Nearby food: ${matchedPlace.nearby_restaurants.slice(0, 2).join(', ')}`
                    : '';

                activitiesHtml += `
                    <div class="relative pl-10 mb-8 last:mb-0">
                        <div class="absolute w-3 h-3 bg-white rounded-full mt-1.5 left-2 shadow-[0_0_10px_rgba(255,255,255,0.5)]"></div>
                        <h5 class="text-white font-medium text-lg">${escapeHtml(placeName)}</h5>
                        <p class="text-xs text-mutedText mb-2 mt-1 uppercase tracking-widest font-semibold">${escapeHtml(act.time || 'Flexible Time')} ${act.duration ? '• ' + escapeHtml(act.duration) : ''}</p>
                        <p class="text-gray-300 text-sm leading-relaxed">${escapeHtml(explanation)}</p>
                        ${travelNote ? `<p class="text-xs text-gray-500 mt-2">Transit: ${escapeHtml(travelNote)}</p>` : ''}
                        ${nearbyHint ? `<p class="text-xs text-gray-500 mt-1">${escapeHtml(nearbyHint)}</p>` : ''}
                    </div>
                `;
            });
        
        dayCard.innerHTML = `
            <h4 class="text-xl font-bold text-white mb-6 flex justify-between items-center bg-surface/50 p-4 -mt-6 -mx-6 mb-6 border-b border-surfaceAlt">
                <div class="flex items-center gap-3">
                    <span class="bg-white text-black px-2 py-0.5 rounded text-xs font-bold tracking-widest uppercase">${escapeHtml(day.dayLabel || ('Day ' + (index + 1)))}</span>
                    <span class="text-base">${escapeHtml(day.theme || 'Exploration')}</span>
                </div>
            </h4>
            <div class="space-y-2 relative">
                ${activitiesHtml}
            </div>
        `;
        timelineEl.appendChild(dayCard);
    });

    if (normalizedDays.length === 0) {
        timelineEl.innerHTML = `<div class="bg-surfaceAlt/30 border border-surfaceAlt p-5 rounded-2xl text-sm text-gray-300">Detailed itinerary explanations are unavailable for this response. Please retry once to regenerate richer plan notes.</div>`;
    }

    const placesContainer = rootNode.querySelector('#places-container');
    const placesList = rootNode.querySelector('#places-list');
    if (placesContainer && placesList) {
        placesList.innerHTML = '';
        if (places.length > 0) {
            places.forEach((place, idx) => {
                const rating = place?.rating ? `${place.rating} / 5` : 'N/A';
                const nearbyPlaces = Array.isArray(place?.nearby_places) ? place.nearby_places.slice(0, 3) : [];
                const nearbyRestaurants = Array.isArray(place?.nearby_restaurants) ? place.nearby_restaurants.slice(0, 3) : [];
                const card = document.createElement('div');
                card.className = 'bg-surface border border-surfaceAlt rounded-xl p-4 space-y-2';
                card.innerHTML = `
                    <div class="flex items-start justify-between gap-2">
                        <p class="text-sm font-semibold text-white">${idx + 1}. ${escapeHtml(place?.name || 'Recommended place')}</p>
                        <span class="text-[11px] text-gray-400">⭐ ${escapeHtml(rating)}</span>
                    </div>
                    <p class="text-xs text-gray-400">Best time: ${escapeHtml(place?.best_time || 'Anytime')}</p>
                    <p class="text-xs text-gray-500">${escapeHtml(place?.address || `${cityName}`)}</p>
                    <p class="text-xs text-gray-300 leading-relaxed">${escapeHtml(place?.description || '')}</p>
                    ${nearbyPlaces.length > 0 ? `<p class="text-xs text-gray-400"><span class="text-gray-200">Nearby places:</span> ${escapeHtml(nearbyPlaces.join(', '))}</p>` : ''}
                    ${nearbyRestaurants.length > 0 ? `<p class="text-xs text-gray-400"><span class="text-gray-200">Nearby restaurants:</span> ${escapeHtml(nearbyRestaurants.join(', '))}</p>` : ''}
                `;
                placesList.appendChild(card);
            });
            placesContainer.style.display = '';
        } else {
            placesContainer.style.display = 'none';
        }
    }

    const tipsList = rootNode.querySelector('#tips-list');
    tipsList.innerHTML = '';
    const tipSource = Array.isArray(data.travel_tips) ? data.travel_tips : data.pro_tips;
    if (Array.isArray(tipSource)) {
        tipSource.forEach(tip => {
            const li = document.createElement('li');
            li.className = 'flex items-start gap-3';
            li.innerHTML = `<span class="text-white mt-0.5">✦</span><span class="flex-1">${tip}</span>`;
            tipsList.appendChild(li);
        });
    } else {
        rootNode.querySelector('#tips-container').style.display = 'none';
    }

    const vlogList = rootNode.querySelector('#vlog-list');
    vlogList.innerHTML = '';
    if (data.vlog_links && Array.isArray(data.vlog_links)) {
        data.vlog_links.forEach((vlog, idx) => {
            const vlogUrl = typeof vlog === 'string' ? vlog : vlog.url;
            const vlogTitle = typeof vlog === 'string' ? `Travel Vlog ${idx + 1}` : (vlog.title || `Travel Vlog ${idx + 1}`);
            const safeUrl = /^https?:\/\//i.test(vlogUrl || '') ? vlogUrl : '#';
            const li = document.createElement('li');
            li.innerHTML = `<a href="${safeUrl}" target="_blank" class="text-gray-300 hover:text-white transition-colors flex items-center gap-2 group">▶ <span class="truncate">${escapeHtml(vlogTitle)}</span></a>`;
            vlogList.appendChild(li);
        });
    } else if (data.youtube_vlogs && Array.isArray(data.youtube_vlogs)) {
        data.youtube_vlogs.forEach(vlog => {
            const safeUrl = /^https?:\/\//i.test(vlog?.url || '') ? vlog.url : '#';
            const li = document.createElement('li');
            li.innerHTML = `<a href="${safeUrl}" target="_blank" class="text-gray-300 hover:text-white transition-colors flex items-center gap-2 group">▶ <span class="truncate">${escapeHtml(vlog.title || 'Inspiration Video')}</span></a>`;
            vlogList.appendChild(li);
        });
    } else {
        vlogList.innerHTML = `<li class="text-gray-500 italic text-xs">Explore YouTube for ${cityName} travel vlogs!</li>`;
    }

    // PDF/Calendar Logic
    rootNode.querySelector('#export-pdf-btn').addEventListener('click', () => { 
        const element = rootNode.querySelector('#export-content');
        const title = rootNode.querySelector('#result-title').textContent.replace(/ /g, '_');
        html2pdf()
            .set({
                margin: 10,
                filename: `${title}.pdf`,
                image: { type: 'jpeg', quality: 0.98 },
                html2canvas: { scale: 2, useCORS: true, ignoreElements: (node) => node.hasAttribute('data-html2canvas-ignore') },
                jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }    
            })
            .from(element)
            .save();
    });

    rootNode.querySelector('#export-cal-btn').addEventListener('click', () => { 
        const city = requestData.city;
        const calUrl = `https://calendar.google.com/calendar/render?action=TEMPLATE&text=Trip+to+${encodeURIComponent(city)}&details=Check+your+Wanderlust+itinerary!`;
        window.open(calUrl, '_blank');
    });

    setTimeout(() => {
        const map = window.initMap ? window.initMap() : null;
        if (map) {
            map.invalidateSize();
        }

        const placesForMap = Array.isArray(data.places)
            ? data.places
            : (Array.isArray(data.places_metadata) ? data.places_metadata : []);

        if (window.renderMap && placesForMap.length > 0) {
            window.renderMap(placesForMap);
        }
    }, 800);

    const chatContainer = document.getElementById('chat-container');
    setTimeout(() => {
        chatContainer.scrollTo({
            top: chatContainer.scrollHeight,
            behavior: 'smooth'
        });
    }, 100);
}
