// Altitude tape for the HUD navigation group (templates/web/hud/navigation.html).
// Polls for window.AppState.viewer or window.viewer, so it suits every viewer.
(function initAltitudeMeter() {
    console.log('[Altitude Meter] Initializing altitude meter...');
    
    const altitudeTape = document.getElementById('altitudeTape');
    const altitudeValue = document.getElementById('altitudeValue');
    
    if (!altitudeTape || !altitudeValue) {
        console.warn('[Altitude Meter] Required elements not found');
        return;
    }
    
    // Generate altitude tape with values
    function generateAltitudeTape() {
        const fragment = document.createDocumentFragment();
        
        // Generate altitude values from 0 to 100,000 feet in 100 ft increments
        for (let alt = 0; alt <= 100000; alt += 100) {
            const div = document.createElement('div');
            div.className = 'altitude-tape-value';
            
            // Mark every 500 feet as major
            if (alt % 500 === 0) {
                div.classList.add('major');
                div.textContent = alt.toString().padStart(5, '0');
            } else {
                div.textContent = alt.toString();
            }
            
            fragment.appendChild(div);
        }
        
        altitudeTape.appendChild(fragment);
        console.log('[Altitude Meter] Tape generated');
    }
    
    // Update altitude display
    function updateAltitude(altitudeMeters) {
        // Convert meters to feet
        const altitudeFeet = Math.round(altitudeMeters * 3.28084);
        
        // Update digital readout
        altitudeValue.textContent = altitudeFeet.toString().padStart(5, '0');
        
        // Update tape position (each tape value is 20px high)
        const tapeIndex = Math.floor(altitudeFeet / 100);
        const offset = 40 - (tapeIndex * 20); // Center at pointer (40px from top)
        altitudeTape.style.transform = `translateY(${offset}px)`;
    }
    
    // Start monitoring altitude
    function startAltitudeMonitoring() {
        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer) {
            setTimeout(startAltitudeMonitoring, 500);
            return;
        }
        
        // Update altitude every frame
        viewer.scene.preRender.addEventListener(() => {
            const position = viewer.camera.positionCartographic;
            if (position) {
                updateAltitude(position.height);
            }
        });
        
        console.log('[Altitude Meter] Monitoring started');
    }
    
    // Initialize
    generateAltitudeTape();
    startAltitudeMonitoring();
    
    console.log('[Altitude Meter] Altitude meter initialized');
})();
