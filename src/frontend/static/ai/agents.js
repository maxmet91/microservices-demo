(function(){
  const baseUrl = document.querySelector('body') ? document.querySelector('body').getAttribute('data-base') || '' : '';
  const container = document.getElementById('ai-helper');
  if(!container) return;

  const discoverBtn = document.getElementById('ai-discover-btn');
  const optionsDiv = document.getElementById('ai-options');
  const statusDiv = document.getElementById('ai-status');
  const gallery = document.getElementById('ai-gallery');
  const imagesDiv = document.getElementById('ai-images');
  // Lightbox elements (created lazily)
  let lightboxEl = null;
  let lightboxImg = null;

  let sessionId = null;
  const shownImages = new Set();

  function setStatus(msg, css){
    if(!statusDiv) return;
    statusDiv.textContent = msg || '';
    statusDiv.className = 'mt-2 text-muted ' + (css || '');
    statusDiv.setAttribute('role','status');
    statusDiv.setAttribute('aria-live','polite');
  }

  function makeSpinner(size='inline'){
    const span = document.createElement('span');
    span.className = 'ai-inline-spinner';
    span.setAttribute('aria-label','Loading');
    return span;
  }

  async function fetchUserAssets(){
    try {
      const res = await fetch(`${window.location.origin}${baseUrl}/api/uas/assets`);
      if(!res.ok) throw new Error('assets fetch failed');
      const data = await res.json();
      return (data.assets || []).map(a => ({
        id: a.asset_id,
        url: a.ui_url,
        description: a.text || ''
      }));
    } catch(e){
      console.warn('Failed to fetch assets', e); return []; }
  }

  function buildDiscoverPayload(assets){
    return {
      product: {
        title: container.dataset.productTitle,
        description: container.dataset.productDescription,
        image: { id: container.dataset.productId, url: container.dataset.productImage }
      },
      assets: assets,
      notes: ''
    };
  }

  function clearOptions(){
    optionsDiv.innerHTML='';
  }

  function renderOptions(options){
    clearOptions();
    if(!options || options.length===0){
      optionsDiv.innerHTML = '<span class="ai-error">No suitable options were found for this product and your photos.</span>';
      return;
    }
    options.forEach(opt => {
      const btn = document.createElement('button');
      btn.className='cymbal-button-secondary mr-2 mb-2';
      btn.textContent = opt.title || opt.option_id;
      btn.dataset.optionId = opt.option_id;
      btn.addEventListener('click', ()=> executeOption(btn, opt.option_id));
      optionsDiv.appendChild(btn);
    });
  }

  function replaceWithSpinner(el){
    const spinner = makeSpinner();
    spinner.style.marginLeft = '0';
    el.replaceWith(spinner);
    return spinner;
  }

  async function discover(){
    if(!discoverBtn) return;
    discoverBtn.disabled = true;
    const spinner = makeSpinner();
    spinner.style.marginLeft='0';
    discoverBtn.parentNode.insertBefore(spinner, discoverBtn.nextSibling);
    discoverBtn.style.display='none';
    setStatus('Looking for the best options...');
    optionsDiv.style.display='block';
    clearOptions();
    const assets = await fetchUserAssets();
    const payload = buildDiscoverPayload(assets);
    try {
      const res = await fetch(`${window.location.origin}${baseUrl}/api/agents/discover`,{
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)
      });
      if(!res.ok) throw new Error('discover failed');
      const data = await res.json();
      sessionId = data.session_id;
      spinner.remove();
      renderOptions(data.options);
      setStatus(data.options && data.options.length ? 'Select an option to generate an image.' : 'No options available.');
    } catch(e){
      console.error(e);
      spinner.remove();
      setStatus('We could not get options for this product and your images.', 'ai-error');
      // Allow retry by showing the button again
      discoverBtn.style.display='inline-block';
      discoverBtn.disabled = false;
    }
  }

  function buildImageCard(finalUrl, idx){
    const card = document.createElement('div');
    card.className='ai-image-card';
    const badge = document.createElement('div');
    badge.className='ai-badge';
    badge.textContent = 'AI';
    const img = document.createElement('img');
    img.loading='lazy';
    img.alt='Generated preview '+ (idx+1);
    img.src = finalUrl;
    img.style.cursor = 'pointer';
    img.addEventListener('click', ()=> openLightbox(finalUrl));
    card.appendChild(img);
    card.appendChild(badge);
    return card;
  }

  function resolveArtifactUrl(imgUrl){
    if(imgUrl.startsWith('http')) return imgUrl;
    let finalUrl = imgUrl;
    if(imgUrl.startsWith('/artifacts/')){
      const parts = imgUrl.split('?');
      const pathPart = parts[0].replace('/artifacts/','');
      const qp = parts.length>1 ? ('?'+parts[1]) : '';
      finalUrl = `${baseUrl}/api/agents/artifacts/${pathPart}${qp}`;
    } else {
      finalUrl = baseUrl + imgUrl; // fallback
    }
    return window.location.origin + finalUrl;
  }

  async function executeOption(btnEl, optionId){
    if(!sessionId){ setStatus('No session. Please retry.', 'ai-error'); return; }
    const spinner = replaceWithSpinner(btnEl);
    setStatus('Generating image...');
    const body = { session_id: sessionId, option_id: optionId };
    try {
      const res = await fetch(`${window.location.origin}${baseUrl}/api/agents/execute`,{
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)
      });
      if(!res.ok) throw new Error('execute failed');
      const data = await res.json();
      spinner.remove();
      if(data.images && data.images.length){
        gallery.style.display='block';
        // ensure square mode & size (half product image width)
        if(!imagesDiv.classList.contains('ai-square')){
          imagesDiv.classList.add('ai-square');
        }
        try {
          const prodImg = document.querySelector('.product-image');
          if(prodImg){
            const w = prodImg.getBoundingClientRect().width;
            const target = Math.max(120, Math.round(w/2));
            imagesDiv.style.setProperty('--ai-preview-size', target + 'px');
          }
        } catch(_e){}
        data.images.forEach((imgUrl, idx) => {
          const resolved = resolveArtifactUrl(imgUrl);
          if(shownImages.has(resolved)) return; // avoid duplicates
            shownImages.add(resolved);
            imagesDiv.appendChild(buildImageCard(resolved, idx));
        });
        // After successful generation hide remaining options to focus on preview
        optionsDiv.style.display='none';
        setStatus('Image generated.');
      } else {
        setStatus(data.message || 'No image returned.', 'ai-error');
      }
    } catch(e){
      console.error(e);
      spinner.remove();
      setStatus('Failed to generate image.', 'ai-error');
    }
  }

  function ensureLightbox(){
    if(lightboxEl) return;
    lightboxEl = document.createElement('div');
    lightboxEl.id='ai-lightbox';
    lightboxEl.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;z-index:9999;padding:40px;';
    lightboxEl.addEventListener('click', closeLightbox);
    lightboxImg = document.createElement('img');
    lightboxImg.style.maxWidth='90%';
    lightboxImg.style.maxHeight='90%';
    lightboxImg.style.borderRadius='12px';
    lightboxImg.style.boxShadow='0 4px 18px rgba(0,0,0,0.4)';
    lightboxEl.appendChild(lightboxImg);
    document.body.appendChild(lightboxEl);
    document.addEventListener('keydown', (e)=>{ if(e.key==='Escape') closeLightbox(); });
  }

  function openLightbox(url){
    ensureLightbox();
    lightboxImg.src=url;
    lightboxEl.style.display='flex';
  }

  function closeLightbox(){
    if(lightboxEl) lightboxEl.style.display='none';
  }

  discoverBtn?.addEventListener('click', discover);
})();
