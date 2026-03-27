"""
Agent skill definitions — structured playbooks for common scenarios.

Architecture: progressive loading
─────────────────────────────────
1. System prompt only contains a SHORT skill catalogue (name + trigger).
2. Agent recognises a matching trigger on the page.
3. Agent calls load_skill("Skill Name") tool → gets the full step-by-step playbook.
4. Agent executes the steps.

This keeps the base system prompt small and only loads detail when needed.

To add a new skill: append a dict to SKILLS with name, trigger, steps.
"""

SKILLS = [
    {
        "name": "Cookie Consent / Banner Dismissal",
        "trigger": "A cookie banner STILL blocks the page after navigate (auto-dismissal failed).",
        "steps": [
            "Note: navigate auto-dismisses most cookie banners. This skill is a FALLBACK for ones it missed.",
            "Take a screenshot to see the exact banner.",
            "Try clicking buttons with text: 同意, 接受, 確定, Accept, I Agree, Got it, OK, Allow All.",
            "Try CSS selectors: [id*='cookie'] button, [class*='consent'] button, #onetrust-accept-btn-handler.",
            "If nothing works: evaluate_javascript(\"document.querySelector('[class*=\\\"cookie\\\"], [class*=\\\"consent\\\"], [class*=\\\"gdpr\\\"]')?.remove()\")",
        ],
    },
    {
        "name": "Autocomplete / Search Suggestions",
        "trigger": "After typing in a search field, an autocomplete dropdown or suggestion list appears that must be interacted with before proceeding.",
        "steps": [
            "After filling a search/destination field, ALWAYS wait 1 second for suggestions to appear.",
            "Call get_page_content to see the suggestion list items.",
            "Click the most relevant suggestion from the dropdown. Look for: [role='option'], li inside [role='listbox'], [class*='suggestion'] li, [data-testid*='suggestion'].",
            "If you cannot find the suggestion items, use evaluate_javascript: document.querySelector('[role=\"listbox\"] [role=\"option\"], [class*=\"suggestion\"] li')?.click()",
            "NEVER try to click other elements while the dropdown is open — it will intercept all clicks.",
            "If you need to dismiss the dropdown without selecting, press Escape first.",
            "After selecting a suggestion, call get_page_content to verify the field was populated correctly.",
        ],
    },
    {
        "name": "Popup / Overlay Dismissal",
        "trigger": "A promotional modal, newsletter signup, notification permission, or overlay blocks the page content.",
        "steps": [
            "Look for close buttons: X icon, 'Close', 'No thanks', 'Maybe later', 'Dismiss'.",
            "Try CSS selectors: .modal .close, [aria-label='Close'], button[class*='close'], .overlay .dismiss.",
            "Try pressing Escape key to close the modal.",
            "If nothing works, try evaluate_javascript: document.querySelector('.modal, .overlay, [class*=\"popup\"]')?.remove()",
            "After dismissal, call get_page_content to verify the page is now accessible.",
        ],
    },
    {
        "name": "Avoid Blocked Services",
        "trigger": "Task involves Google services (Google Search, Gmail, Google Docs, NotebookLM, YouTube login) or any site that aggressively blocks bots.",
        "steps": [
            "NEVER navigate to google.com for web searches — use DuckDuckGo (duckduckgo.com/?q=...).",
            "NEVER try to log into Google accounts — it WILL block automated browsers. If login is required, call request_human_assistance and explain the limitation.",
            "For Google services that have free/no-login alternatives, use those instead:",
            "  - NotebookLM: https://notebooklm.google.com (free version, may not require login)",
            "  - Google Translate: use DuckDuckGo or navigate to translate.google.com (works without login)",
            "  - YouTube: viewing videos works without login, only comments/uploads need login",
            "For creating presentations/slides: if NotebookLM requires login, suggest alternatives to the user via ask_user: 'NotebookLM requires Google login which I cannot automate. Alternatives: (1) I can generate slide content as text, (2) I can use another presentation tool.'",
            "For creating documents: suggest Google Docs alternatives that don't require login.",
            "General rule: if you hit a login wall or CAPTCHA on Google, do NOT waste iterations trying to bypass it. Immediately inform the user and suggest an alternative approach.",
        ],
    },
    {
        "name": "Auth: Identify Login Type",
        "trigger": "Page shows any kind of login, sign-in, or authentication requirement.",
        "steps": [
            "Call get_page_content and take_screenshot to understand the auth page.",
            "Classify the auth type by looking for these patterns:",
            "  - Standard form: visible email/username + password fields on SAME page → use load_skill('Auth: Standard Login Form').",
            "  - Multi-step form: only email/username visible, no password yet (Google/Microsoft style) → use load_skill('Auth: Multi-Step Login').",
            "  - OAuth / Social buttons: 'Sign in with Google', 'Continue with Facebook', GitHub icon, etc → use load_skill('Auth: OAuth / Social Login').",
            "  - SSO / Enterprise: 'Sign in with SSO', company domain input, or SAML redirect → use load_skill('Auth: SSO / Enterprise').",
            "  - Magic link / passwordless: 'We will send you a link', 'Check your email' → use load_skill('Auth: Magic Link / Email Verification').",
            "  - Phone + OTP: phone number input, 'Send code via SMS' → use load_skill('Auth: Phone OTP').",
            "Always load the specific auth skill BEFORE attempting to interact with the form.",
        ],
    },
    {
        "name": "Auth: Standard Login Form",
        "trigger": "Page has email/username AND password fields visible on the same page.",
        "steps": [
            "Identify the exact selectors: input[type='email'], input[name*='user'], input[name*='login'], input[type='password'].",
            "Do NOT guess or fabricate credentials.",
            "Call request_credentials with fields matching what the page needs. Example: fields=[{name:'email', label:'Email', type:'email'}, {name:'password', label:'Password', type:'password'}].",
            "Parse the JSON response and fill each field using fill(selector, value).",
            "Look for the submit button: button[type='submit'], input[type='submit'], or button with text 'Log in', 'Sign in'.",
            "Click the submit button.",
            "Wait 2-3 seconds, then call get_page_content to check the result.",
            "If you see an error message like 'Invalid password', inform the user via request_human_assistance.",
            "If 2FA/MFA is shown after login, load_skill('Auth: Two-Factor / MFA').",
        ],
    },
    {
        "name": "Auth: Multi-Step Login",
        "trigger": "Login form shows only email/username first, password appears on next step (Google, Microsoft, Yahoo style).",
        "steps": [
            "Step 1 — Email: call request_credentials with fields=[{name:'email', label:'Email or Username', type:'email'}].",
            "Fill the email field and click Next/Continue.",
            "Wait for the page to transition — use wait_for_element to detect the password field appearing.",
            "Step 2 — Password: call request_credentials with fields=[{name:'password', label:'Password', type:'password'}].",
            "Fill the password field and click Next/Sign in.",
            "Wait for the page to transition.",
            "If a 'Choose account' or 'account picker' page appears, call get_page_content to list accounts and request_human_assistance to ask which one.",
            "If 2FA/MFA is shown, load_skill('Auth: Two-Factor / MFA').",
            "Verify login success by checking if the URL changed away from the login domain.",
        ],
    },
    {
        "name": "Auth: OAuth / Social Login",
        "trigger": "Page shows 'Sign in with Google/Facebook/GitHub/Apple/Twitter' buttons or OAuth redirect.",
        "steps": [
            "Call get_page_content and list all social login options visible.",
            "Call request_human_assistance with reason: 'Multiple login options available: [list them]. Which method should I use? If using social login, you may need to complete the OAuth flow manually.'",
            "If the operator says to use a social provider: click that button.",
            "The browser will redirect to the OAuth provider (Google, Facebook, etc).",
            "On the provider page, use load_skill('Auth: Identify Login Type') again — it will likely be a multi-step login.",
            "After OAuth completes, the browser will redirect back to the original site.",
            "Call get_page_content to verify login success.",
            "If a consent/permissions screen appears ('Allow access to...'), call request_human_assistance to ask if the user wants to allow.",
        ],
    },
    {
        "name": "Auth: SSO / Enterprise",
        "trigger": "Page shows SSO login, company domain input, SAML redirect, or 'Sign in with your organization'.",
        "steps": [
            "Call request_credentials with fields=[{name:'domain', label:'Company Domain or SSO Email', type:'email'}].",
            "Fill the domain/email field and submit.",
            "The page will likely redirect to a corporate identity provider (Okta, Azure AD, Auth0, etc).",
            "On the IdP page, use load_skill('Auth: Identify Login Type') again to handle that login form.",
            "After SSO completes, the browser will redirect back to the original site.",
            "If the IdP uses a method you cannot handle (hardware key, biometric), call request_human_assistance.",
        ],
    },
    {
        "name": "Auth: Magic Link / Email Verification",
        "trigger": "Page says 'We sent you a link', 'Check your email', 'Passwordless login', or only asks for email with no password field.",
        "steps": [
            "This flow requires the user to check their email — the agent cannot do this.",
            "Call request_human_assistance with reason: 'This site uses passwordless/magic link login. Please: (1) check your email for the login link, (2) click it in your browser, (3) once logged in, let me know to continue.'",
            "Alternatively, if the page offers other login methods (password, social), suggest those.",
            "If the user wants to proceed with magic link, wait for their response confirming they've clicked the link.",
            "After the user confirms, call get_page_content to verify login success.",
        ],
    },
    {
        "name": "Auth: Phone OTP",
        "trigger": "Page asks for phone number and will send an SMS verification code.",
        "steps": [
            "Call request_credentials with fields=[{name:'phone', label:'Phone Number', type:'text'}].",
            "Fill the phone number and click 'Send Code' or equivalent button.",
            "Wait for the OTP input field to appear: use wait_for_element for input[name*='otp'], input[name*='code'], input[type='number'].",
            "Call request_credentials with fields=[{name:'otp', label:'SMS Verification Code', type:'number'}].",
            "Fill the OTP and submit.",
            "Verify login success with get_page_content.",
        ],
    },
    {
        "name": "Auth: Two-Factor / MFA",
        "trigger": "After entering password, page asks for 2FA: TOTP code, SMS code, authenticator app, or security key.",
        "steps": [
            "Take a screenshot to show the user what 2FA method is being requested.",
            "Identify the 2FA type from the page content:",
            "  - Authenticator app / TOTP: ask for 6-digit code.",
            "  - SMS code: the site already sent it; ask user to check their phone.",
            "  - Email code: ask user to check their email.",
            "  - Security key / biometric: cannot be done by agent — request_human_assistance.",
            "For code-based 2FA: call request_credentials with fields=[{name:'code', label:'2FA Code (from your authenticator or SMS)', type:'number'}].",
            "Fill the code and submit.",
            "If 'Trust this device' or 'Remember this browser' checkbox appears, click it.",
            "Verify login success with get_page_content.",
        ],
    },
    {
        "name": "CAPTCHA Handling",
        "trigger": "Page shows a CAPTCHA or bot verification challenge (reCAPTCHA, hCaptcha, Cloudflare, image CAPTCHA, 驗證碼, press-and-hold, slider).",
        "steps": [
            "FIRST take_screenshot to identify the challenge type:",
            "  - Simple image CAPTCHA (distorted text/numbers, 驗證碼): load_skill('Image CAPTCHA / Verification Code').",
            "  - reCAPTCHA / hCaptcha / Turnstile checkbox: call solve_captcha for automatic solving.",
            "  - 'Press and hold' button: use click(selector, hold_ms=3000). Hold for 3-5 seconds.",
            "  - Slider verification: use mouse actions — find the slider handle, click_position to drag it across.",
            "If solve_captcha returns [CAPTCHA_UNSOLVED], call request_human_assistance.",
            "After ANY verification is resolved, take_screenshot to confirm the page progressed.",
        ],
    },
    {
        "name": "Image CAPTCHA / Verification Code",
        "trigger": "Page has a simple image CAPTCHA showing distorted text/numbers that must be typed in (common on Taiwan, China, Japan websites — 驗證碼, 验证码).",
        "steps": [
            "Take a screenshot with take_screenshot() — the image will be visible to you.",
            "Look at the CAPTCHA image in the screenshot. Read the numbers/letters shown.",
            "Find the CAPTCHA input field (usually near the CAPTCHA image): input[name*='captcha'], input[name*='verify'], input[name*='code'], input[id*='captcha'].",
            "Fill the input with the text you read from the image.",
            "Submit the form (click submit button or press Enter).",
            "If the CAPTCHA was wrong (page shows error or same CAPTCHA again), the image may have changed — take a NEW screenshot and try again.",
            "You can retry up to 3 times. If still failing, call request_human_assistance.",
        ],
    },
    {
        "name": "Search Pattern",
        "trigger": "Task requires searching the web for information, or you need to look something up.",
        "steps": [
            "NEVER use Google for web searches — it will block you with CAPTCHA every time.",
            "Use DuckDuckGo instead: navigate to https://duckduckgo.com/?q=YOUR+SEARCH+QUERY (URL-encode the query).",
            "Call get_page_content to read the search results.",
            "If searching WITHIN a specific website (e.g. 'search on Amazon'), go directly to that site and use its search box.",
            "If the task says 'Google something', still use DuckDuckGo — the user means 'search the web', not specifically google.com.",
        ],
    },
    {
        "name": "Infinite Scroll / Lazy Loading",
        "trigger": "Need to see more content on a page that loads dynamically (social media feeds, product listings, search results with no pagination buttons).",
        "steps": [
            "Scroll down to trigger lazy loading.",
            "Wait 1-2 seconds for new content to load (use wait_for_element if a specific element is expected).",
            "Call get_page_content to read the newly loaded content.",
            "Repeat scroll + read until the desired content is found or sufficient data is collected.",
            "Stop after 5 scroll attempts if no new content appears.",
        ],
    },
    {
        "name": "Navigation Error Recovery",
        "trigger": "Page returns 404, 403, 500, or 'Access Denied', or the page is blank/broken.",
        "steps": [
            "Take a screenshot to document the error state.",
            "Check the current URL — it may have been redirected.",
            "If 404: verify the URL is correct, try the site's homepage and navigate from there.",
            "If 403/Access Denied: the site may be blocking automated access. Try a different approach or request_human_assistance.",
            "If 500: wait 3 seconds and retry the navigation once.",
            "If the page is blank: wait for content with wait_for_element('body *', timeout=10000), then try get_page_content.",
        ],
    },
    {
        "name": "Data Extraction",
        "trigger": "Task requires extracting structured data from a page (prices, names, lists, table data).",
        "steps": [
            "Call get_page_content first to understand the page structure.",
            "If the data is in a table, use evaluate_javascript to extract it: document.querySelectorAll('table tr') and map over cells.",
            "If the data is in a list or repeated elements, identify the pattern and use evaluate_javascript to extract all items.",
            "Scroll down to check if there is more data below the fold.",
            "Format the extracted data clearly in your final summary.",
        ],
    },
    {
        "name": "Date Picker Handling",
        "trigger": "Need to select or change a date in any date picker, calendar widget, or date input field.",
        "steps": [
            "NEVER try to click through a calendar widget day by day — it is unreliable and slow.",
            "",
            "Step 1 — Discover date inputs on the page:",
            "  evaluate_javascript(\"JSON.stringify([...document.querySelectorAll('input')].filter(e => e.type==='text' || e.type==='date' || e.readOnly).filter(e => e.id.match(/date/i) || e.name.match(/date/i) || e.placeholder?.match(/date|日期|yyyy/i) || e.value.match(/\\\\d{4}[\\\\/-]/)).map(e => ({tag:'input', id:e.id, name:e.name, type:e.type, value:e.value, readOnly:e.readOnly})))\")",
            "  This finds ALL date-related inputs on the page with their current values.",
            "",
            "Step 2 — Set the date using the BEST strategy:",
            "",
            "  Strategy A — JS injection (try first, works on most sites):",
            "    Use the id/name you found in Step 1. Try setting the value with native setter + dispatch events:",
            "    evaluate_javascript(\"const el=document.getElementById('ID_FROM_STEP1'); const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; s.call(el,'TARGET_DATE'); el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); el.value\")",
            "    Try multiple date formats: YYYY/MM/DD, YYYY-MM-DD, MM/DD/YYYY, DD/MM/YYYY — check what format the current value uses.",
            "",
            "  Strategy B — <select> dropdowns (if year/month/day are separate selects):",
            "    Use select_option for each dropdown. Discover them with get_page_content.",
            "",
            "  Strategy C — Calendar widget (last resort):",
            "    take_screenshot → find and click the calendar icon → take_screenshot → click_position on the target date cell.",
            "    If wrong month shown, click next/prev arrows to navigate.",
            "",
            "Step 3 — Verify: ALWAYS take_screenshot after setting to confirm the date changed.",
            "Step 4 — If unchanged, try a different format or strategy. Many readonly inputs ignore JS value changes — use Strategy C.",
        ],
    },
    {
        "name": "Travel / Hotel Booking Site",
        "trigger": "Task involves searching for hotels, flights, or accommodation on any travel/booking website.",
        "steps": [
            "IMPORTANT: Travel sites have complex date pickers. Never click calendar day-by-day. Use load_skill('Date Picker Handling').",
            "Best approach: try to build a search URL with parameters and navigate directly. Most travel sites support URL params for destination, check-in/out dates, and guest count.",
            "  To discover URL format: first do a manual search on the site, then look at the resulting URL to understand the parameter pattern.",
            "  Common parameter names: ss/q/destination (city), checkin/checkIn/startDate, checkout/checkOut/endDate, adults/group_adults, rooms/no_rooms.",
            "If URL approach doesn't work, use the search form: fill the destination → wait for autocomplete (fill() auto-selects first suggestion) → set dates via JS → submit.",
            "After search results load, scroll + get_page_content to read. Travel sites lazy-load results.",
            "If comparing prices, use evaluate_javascript to extract price data from all visible result cards.",
            "Use reasonable defaults if not specified: tomorrow check-in, day-after checkout, 2 adults, 1 room.",
        ],
    },
    {
        "name": "Search Results Filtering",
        "trigger": "Task requires filtering or narrowing results by criteria (star rating, price range, category, brand, size, color, amenities, etc) on any listing/search page.",
        "steps": [
            "After search results load, take_screenshot to see the full page layout — filters are usually in a sidebar (left or top).",
            "Use get_page_content to find filter elements. Common patterns:",
            "  - Checkboxes: input[type='checkbox'] near label text (e.g. '5 stars', 'Free WiFi', 'Pool')",
            "  - Price sliders: input[type='range'] or draggable elements",
            "  - Dropdowns: <select> for 'Sort by' (price low-to-high, rating, etc)",
            "  - Clickable filter chips/tags: buttons or links with filter labels",
            "To apply a checkbox filter: click the checkbox or its label text. Example: click('5 stars') or click the label closest to the checkbox.",
            "To apply a sort: look for 'Sort by' dropdown and use select_option, or click the sort option directly.",
            "For price range: if it's a slider, use evaluate_javascript to set min/max values. If it's input fields, use fill.",
            "After applying each filter, wait for results to reload — the page usually does an AJAX refresh. Use get_page_content to verify the filtered results.",
            "Take take_screenshot after filtering to capture evidence of the filtered results.",
            "If the task specifies multiple criteria (e.g. '5-star, pool, under $200'), apply them one at a time and verify after each.",
        ],
    },
    {
        "name": "Transportation / Ticket Booking",
        "trigger": "Task involves booking train/bus/flight tickets, checking timetables, or searching schedules on any transportation website (高鐵, 台鐵, JR, airlines, etc).",
        "steps": [
            "Step 1 — Start from the official homepage. Do NOT guess internal URLs.",
            "  Navigate to the main page (e.g. thsrc.com.tw for 台灣高鐵).",
            "  take_screenshot to verify you're on the correct site.",
            "",
            "Step 2 — The homepage often HAS the search form directly (e.g. THSR has '時刻表與票價' tab with form on homepage).",
            "  Do NOT click away to internal pages. First check if the homepage already has the form:",
            "  Use evaluate_javascript to discover ALL form fields:",
            "  evaluate_javascript(\"JSON.stringify([...document.querySelectorAll('select')].map(s=>({tag:'select',id:s.id,value:s.value,options:[...s.options].map(o=>o.text).slice(0,12)})).concat([...document.querySelectorAll('input:not([type=hidden])')].map(i=>({tag:'input',id:i.id,type:i.type,value:i.value,readOnly:i.readOnly}))))\")",
            "  This tells you all select dropdowns (with their options) and inputs on the page.",
            "",
            "Step 3 — Fill the form using the discovered IDs.",
            "  For <select> dropdowns: IMPORTANT — the option VALUE may differ from the display text.",
            "  First discover exact option values: evaluate_javascript(\"JSON.stringify([...document.getElementById('SELECT_ID').options].map(o=>({value:o.value,text:o.text})))\")",
            "  Then use select_option with the display TEXT (not the value): select_option('#select_id', '新竹')",
            "  Date inputs: if readOnly=false, use fill('#date_id', 'YYYY/MM/DD') or evaluate_javascript to set value.",
            "  Time inputs: fill('#time_id', 'HH:MM').",
            "  CRITICAL: date defaults to TODAY. You MUST change it to the correct date.",
            "",
            "Step 4 — take_screenshot to verify ALL fields before submitting.",
            "  Check: correct stations, correct date (not today!), correct time.",
            "  If the date still shows today, it was NOT set correctly — retry with JS injection.",
            "",
            "Step 5 — CAPTCHA if present: take_screenshot → read characters → fill.",
            "",
            "Step 6 — Click submit/search button.",
            "  IMPORTANT: if click fails (intercepted by carousel/overlay), use evaluate_javascript(\"document.getElementById('BUTTON_ID').click()\") instead.",
            "  take_screenshot to see results. If 'no results' or 'sold out', try adjusting time or date.",
        ],
    },
    {
        "name": "Form Filling",
        "trigger": "Task requires filling out a multi-field form (registration, booking, application).",
        "steps": [
            "Call get_page_content to identify all form fields.",
            "Fill fields in order from top to bottom.",
            "For <select> dropdowns, use select_option instead of click.",
            "For radio buttons and checkboxes, use click with the specific input selector.",
            "For date pickers, load_skill('Date Picker Handling') — never click through calendar widgets.",
            "After filling all fields, take a screenshot to verify before submitting.",
            "If any required information is missing from the task prompt, call ask_user to ask.",
        ],
    },
    {
        "name": "Complex Web App Interaction",
        "trigger": "Task involves a complex SPA or web app with dynamic panels, menus, and modals (e.g., NotebookLM, Google Docs, Figma, Notion, Canva).",
        "steps": [
            "These apps have complex, dynamic UIs. Do NOT assume you know the layout — explore first.",
            "After navigating, take_screenshot to see the actual UI (get_page_content often misses SPA elements).",
            "If login is required and it's a Google service, load_skill('Avoid Blocked Services').",
            "Explore the UI step by step: take_screenshot → identify buttons/menus → click one → take_screenshot → observe result.",
            "For creating content (slides, docs, etc): look for 'New', '+', or 'Create' buttons. Use get_page_content to find them.",
            "For adding data/sources: look for 'Add', 'Import', 'Upload' buttons or drag-and-drop areas.",
            "For generating output (export, download): look for menu items, '...' buttons, or 'Share'/'Export' options.",
            "Use take_screenshot frequently — SPAs change state without URL changes, so page brief alone is not enough.",
            "If the app has a sidebar or panel layout, scroll within panels (not just the main page) to find hidden options.",
        ],
    },
    {
        "name": "File Download",
        "trigger": "Task requires downloading a file (PDF, CSV, image, document, attachment).",
        "steps": [
            "If the URL directly points to a file (e.g. ends in .pdf, .csv, .zip), use download_file(url=...) — this downloads it directly without needing to navigate.",
            "If the download is triggered by a button or link on a page, use download_file(selector=...) — this clicks the element and captures the download.",
            "NEVER use evaluate_javascript or plain click to download files — only download_file actually saves the file to disk.",
            "If the page requires login or form submission before downloading, complete those steps first.",
            "After download_file returns, verify it reports a file name and size. Only then report success.",
            "If download_file returns an error, try an alternative approach or request_human_assistance.",
        ],
    },
    {
        "name": "Multi-Page Navigation",
        "trigger": "Task requires visiting multiple pages or pagination (e.g. 'check the first 3 pages of results').",
        "steps": [
            "Process the current page fully before navigating to the next.",
            "Look for 'Next' buttons, page number links, or pagination controls.",
            "Use get_page_content after each page navigation to read the new content.",
            "Keep a mental note of data collected from each page.",
            "Combine results from all pages in your final summary.",
        ],
    },
    {
        "name": "Evidence Collection",
        "trigger": "Task is nearing completion and you need to capture verifiable proof of the results.",
        "steps": [
            "Evidence screenshots must show the ACTUAL results the user asked for, not just any page.",
            "Step 1 — Identify what needs to be captured: if user asked for 3 hotels, you need screenshots showing all 3.",
            "Step 2 — Capture with scrolling: take_screenshot → scroll down → take_screenshot → repeat until all results are covered.",
            "Step 3 — Verify each screenshot in your reasoning: describe what each screenshot shows. If two screenshots look identical, scroll further and retake.",
            "Step 4 — For long lists, extract the key data BEFORE screenshotting: use get_page_content or evaluate_javascript to read prices/names/ratings, then take_screenshot of each result section.",
            "Step 5 — For multi-page results (pagination), capture the most relevant page, not all pages.",
            "Common pattern: scroll(direction='down', amount=600) → take_screenshot → scroll(direction='down', amount=600) → take_screenshot.",
            "Duplicate screenshots are auto-filtered. Only unique screenshots are saved.",
        ],
    },
    {
        "name": "Self-Healing / Error Recovery",
        "trigger": "A tool returns an [ERROR:...] tag, a ⚠ WARNING about repeated actions, or [ERROR:loop_detected].",
        "steps": [
            "Read the error tag to understand the failure type:",
            "  - [ERROR:element_not_found] → call get_page_content to see what IS on the page, pick a different selector.",
            "  - [ERROR:navigation_timeout] → retry once. If still fails, try the site homepage first.",
            "  - [ERROR:network] → the URL is wrong or the site is down. Verify and try an alternative.",
            "  - [ERROR:page_crashed] → call get_page_content to see current state. The page may have redirected.",
            "  - [ERROR:wrong_element] → you used the wrong tool for this element type. Re-read the page and adapt.",
            "  - [ERROR:loop_detected] → you are stuck in a loop. STOP and do something completely different.",
            "If you see ⚠ WARNING about repeated actions: you are about to enter a loop. IMMEDIATELY change your approach.",
            "After ANY error, always call get_page_content before retrying — the page may have changed.",
            "If stuck: (1) take_screenshot to see the real page state, (2) try evaluate_javascript as alternative, (3) call request_human_assistance as last resort.",
            "NEVER repeat the exact same failed action — always change the selector, tool, or entire strategy.",
        ],
    },
]

# ── Lookup by name ──────────────────────────────────────────────────
_SKILL_MAP = {s["name"]: s for s in SKILLS}


def get_skill(name: str) -> str | None:
    """Return the full playbook for a skill by name, or None if not found."""
    skill = _SKILL_MAP.get(name)
    if not skill:
        # Fuzzy match: check if the query is a substring of any skill name
        for key, val in _SKILL_MAP.items():
            if name.lower() in key.lower():
                skill = val
                break
    if not skill:
        return None
    lines = [f"## Skill: {skill['name']}", f"Trigger: {skill['trigger']}", "Steps:"]
    for i, step in enumerate(skill["steps"], 1):
        lines.append(f"  {i}. {step}")
    return "\n".join(lines)


def build_skill_catalogue() -> str:
    """Short catalogue for the system prompt — names and triggers only."""
    lines = [
        "\n## Available Skills",
        "When you recognise a trigger condition below, call load_skill(name) to "
        "get the full playbook BEFORE acting. This keeps your context lean.\n",
    ]
    for s in SKILLS:
        lines.append(f"- **{s['name']}** — {s['trigger']}")
    return "\n".join(lines)
