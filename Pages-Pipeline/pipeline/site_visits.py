"""The live-site sweep: every aku.edu page opened, what it showed, what it changed.

The two exports say what exists and who owns it. They do not say what AKU thinks
a thing *is* — that only the live site states, in its breadcrumb, its left nav and
the units it names on a landing page. Every row here was fetched, not inferred.

`VISITED` feeds the portal's Live-site checks screen. `REMAINING` is the honest
to-do list: the sweep is not finished, and this file says exactly what is left so
the next pass has no guesswork in it.

Run: python site_visits.py   -> ../out/aku-site-visits.csv
"""
import csv
import os

import paths

# url path, what AKU showed, what it settled, and whether it changed a placement
VISITED = [
    # --- the two lists that decide what an entity is -----------------------
    ('/academics', 'Academic units by country: PK — SONAM, Medical College, IED, FAS; '
     'KE — SONAM, MC, GSMC, IHD; TZ — SONAM, MC, IED; UG — SONAM; UK — ISMC',
     'The authoritative entity list. On this list = entity; not on it = a folder.', 'yes'),
    ('/research', 'Global Institutes & Centres: ACER, Brain & Mind Institute, CIME, '
     'COE-WCH, IGHD, IHD. Plus Clinical Research Unit Kenya, Clinical Trials Unit Pakistan',
     'Six bodies are global by AKU’s own framing, so they belong to no country.', 'yes'),

    # --- country landing pages --------------------------------------------
    ('/pakistan', 'Home > Pakistan. Names SONAM, Medical College, IED, FAS, '
     'Centre for Regenerative Medicine, Centre of Excellence for Trauma & Emergencies',
     'CRM and CETE are published Pakistan units — promoted from region folder to entity.', 'yes'),
    ('/kenya', 'Home > Kenya. Names SONAM, Medical College, GSMC; CRU under research',
     'Confirms the Kenya entity set.', 'no'),
    ('/tanzania', 'Home > Tanzania. Names SONAM, Medical College, IED',
     'Confirms the Tanzania entity set.', 'no'),
    ('/uganda', 'Home > Uganda. Names SONAM only; medicine, education and media are '
     'described as planned expansions',
     'Uganda genuinely has one entity — the empty folders are future, not missing data.', 'no'),
    ('/united-kingdom', 'Home > United Kingdom. Names AKU-ISMC only',
     'Confirms the UK entity set.', 'no'),

    # --- the global institutes, each checked individually ------------------
    ('/bmi', 'Home > Brain & Mind Institute. Nairobi given as primary contact, '
     'Karachi second. Nav: About us, Research, Education, Engagement & partnership',
     'Cross-region, and Nairobi-first — the earlier Pakistan placement was wrong.', 'yes'),
    ('/ihd', 'Home > Institute for Human Development. Nairobi address (Park Place, '
     '2nd Parklands Ave). Nav: About us, Programmes, Projects, Resources',
     'Nairobi-based, not Pakistan — placement corrected.', 'yes'),
    ('/ighd', 'Home > Institute for Global Health & Development. Karachi-based, serving '
     'South and Central Asia and Africa. Nav: About Us, What We Do, Research, '
     'Resources, Opportunities',
     'A global institute that happens to sit in Karachi.', 'yes'),
    ('/cime', 'Home > Centre for Innovation in Medical Education. Nav carries '
     '"Pakistan" and "East Africa" as siblings',
     'It splits by region internally — one centre, regional arms.', 'yes'),
    ('/coe-wch', 'Home > Centre of Excellence in Women and Child Health. One centre '
     'with South & Central Asia and East Africa arms; folders /pk, /ea, /ca',
     'Global, with three regional arms as tags. /ca is Central Asia — a region the '
     'news taxonomy does not have.', 'yes'),
    ('/acer', 'Home > Arusha Climate Environmental Research. Based in Arusha, Tanzania, '
     'on ~4,000 acres. Nav: About Us, Research, Programmes, Partnerships',
     'Named for its place, so it stays in Tanzania despite being on the global list.', 'no'),

    # --- entities whose region was only inferred ---------------------------
    ('/gsmc', 'Home > Graduate School of Media & Communications. Nairobi, University '
     'Centre, Third Parklands Ave. Nav includes Projects > Giving Nature a Voice',
     'Kenya confirmed. Also resolves /GNV: it is a GSMC project, not a standalone campaign.', 'yes'),
    ('/eai', 'Home > The East Africa Institute. No city named; speaks for Kenya, '
     'Uganda, Tanzania and Rwanda',
     'East Africa-wide, not Nairobi-only — moved out of Kenya.', 'yes'),
    ('/mcea', 'Home > Medical College, East Africa. Names the Nairobi and Dar es '
     'Salaam campuses',
     'One entity across two countries — East Africa, not Kenya alone.', 'yes'),
    ('/sonamea', 'School of Nursing & Midwifery, East Africa. Nairobi, Kampala and '
     'Dar es Salaam addresses',
     'A three-country entity.', 'yes'),
    ('/iedea', 'Institute for Educational Development, East Africa. States "Based in '
     'Dar es Salaam, Tanzania"',
     'Settles the question the login domains got backwards (13 Nairobi vs 8 Dar).', 'yes'),
    ('/fasea', 'Home > Faculty of Arts and Sciences, East Africa. No single city named',
     'East Africa; the earlier "planned for Arusha, so Tanzania" guess is dropped.', 'yes'),
    ('/faspk', 'Home > Faculty of Arts and Sciences, Pakistan. Karachi, Stadium Road',
     'Pakistan confirmed. Its page repeats the six global institutes — third confirmation.', 'no'),
    ('/cete', 'Home > Centre of Excellence for Trauma & Emergencies. Karachi, Stadium '
     'Road Campus. Nav: About Us, Research, Programmes, News, Events',
     'Pakistan confirmed, and it is a published Pakistan unit.', 'yes'),

    # --- the university-wide networks --------------------------------------
    ('/qtl', 'Home > Network of Quality, Teaching and Learning. "The AKU-wide Network '
     '… was set up by the Provost in 2013". Mentions Karachi, Nairobi, East Africa',
     'University-wide — global confirmed, no longer inferred.', 'yes'),
    ('/ele-net', 'Home > Network of English Language Enhancement. Spans Pakistan, '
     'East Africa (Kenya, Tanzania), Uganda and the United Kingdom',
     'University-wide — global confirmed, no longer inferred.', 'yes'),

    # --- the global functions, and how they split --------------------------
    ('/', 'Main menu: About Us, Academics, Admissions, Research, Support Us, '
     'Information for (Students, Alumni, Faculty, Media, Careers, Libraries)',
     'The six top-level menus, which set the order every folder now lists in.', 'yes'),
    ('/about', 'Home > About AKU. Nav: Why AKU?, Our Impact, Administrative Offices, '
     'AKU & Environment',
     'The section nav differs from the top-menu About submenu; both are legitimate.', 'no'),
    ('/admissions', 'Home > Admissions. Programmes by degree level (Undergraduate, '
     'Graduate, Doctoral) AND Campuses by country (PK, UG, KE, TZ, UK)',
     'Admissions splits on two axes at once — degree level and campus.', 'yes'),
    ('/students', 'Home > Students. Student Experience, Counselling & Wellness, '
     'Physical Health, Accommodations — each split Home/KE/PK/TZ/UG',
     'Region is an inner level of a global function, not the root.', 'yes'),
    ('/students/wellness/pk/about', 'Home > Students > Counselling Services & Wellness '
     '> Pakistan > About Us',
     'Confirms the country level sits inside the function.', 'yes'),
    ('/library', 'Home > Library. Groups: Pakistan Libraries, East Africa Libraries, '
     'United Kingdom, University-Wide Services',
     'Library is one function with region groupings plus a university-wide bucket.', 'yes'),
    ('/library/ea/gsmc', 'Home > Library > East Africa > Graduate School of Media & '
     'Communications, Nairobi',
     'The cross-entity rule: canonical parent is the Library; entity and region are tags.', 'yes'),
    ('/news', 'Home > News. Filters by Entity and by Tag',
     'AKU already runs news as one hub segregated by tag — so events and blogs '
     'consolidate the same way.', 'yes'),
    ('/blogs', 'Home > Blogs > Blogs, "AKU Blogs", keyword and year filters',
     'A hub, not a per-faculty folder.', 'yes'),

    # --- individual pages that settled a clash -----------------------------
    ('/crm/about/executive-committee.aspx', 'Live page, five committee members',
     'The dot-variant executive.committee.aspx returns 401 and is dropped.', 'yes'),
    ('/library/pk/fhs/Pages/home.aspx', 'Live page, ~800 words on the FHS library',
     'SitePages/Home.aspx is an empty SharePoint default and is dropped.', 'yes'),
    ('/coe-wch/ea/Pages/home-1.aspx', 'HTTP 404',
     'Already gone from the live site though still listed for migration.', 'yes'),
    ('/mrtc-pk/research/Pages/Projects/home.aspx', 'HTTP 404',
     'The one folder with no title in the export; its source page is gone.', 'yes'),

    # --- sections that are not publicly reachable --------------------------
    ('/cancer-centre', 'HTTP 401 — not publicly visible',
     'Its 25 pages are in AKU’s migrate list but the section is not public. AKU has '
     'to say whether it should be.', 'yes'),
    ('/dhrc', 'HTTP 401 — not publicly visible',
     'Same for its 13 pages.', 'yes'),

    # --- one that disagrees with its own permissions -----------------------
    ('/ccit', 'Critical Creative Innovative Thinking. Describes itself as "a unique '
     'innovation and incubation hub" operating sector-agnostically, Karachi',
     'The page reads standalone, but CW/CA MC PK own it. Kept under Medical College '
     'because permissions drive editing rights — flagged as ambiguous.', 'no'),

    # --- second sweep: the global functions --------------------------------
    ('/supportus', 'Home > Support Us. Nav: Give Now, Giving Opportunities, Ways to '
     'Give, Impact of Giving — matching the main menu exactly',
     'University-wide giving. Global confirmed.', 'no'),
    ('/alumni', 'Home > Alumni. Alumni across Pakistan, Uganda, Kenya, Tanzania and '
     'the UK, resident in 57 countries. Names the Pakistan Chapter, Medical College',
     'Global, with alumni/pk-chap as a country chapter inside it.', 'no'),
    ('/careers', 'Home > Careers. University-wide recruitment across the five countries',
     'Global confirmed.', 'no'),
    ('/vacancies', 'Home > Vacancies. Job listings; the page itself points at '
     '/careers/Pages/home.aspx as the parent unit',
     'It duplicates /careers — the two should merge rather than both existing.', 'yes'),
    ('/geo', 'Home > Global Engagement Office. Nav: About GEO, For Students, For '
     'Partners. "a central role in expanding AKU’s global reach", based in Pakistan',
     'A university-wide office. Global confirmed.', 'no'),
    ('/registrar', 'Home > Registrar’s Office. Serves "all academic programmes across '
     'all of the University’s campuses: Pakistan, Kenya, Tanzania, Uganda and the UK"',
     'Global confirmed, in its own words.', 'no'),
    ('/convocation', 'Home > Convocation. Five country sections — Kenya, Pakistan, '
     'Tanzania, Uganda, United Kingdom — each with Read more',
     'Confirms the country split inside a global function.', 'no'),
    ('/leads', 'Home > Lifelong Learning Education & Development of Skills. An online '
     'course platform, university-wide',
     'Global confirmed.', 'no'),
    ('/deib', 'Home > Diversity, Equity, Inclusion & Belonging. Covers "all areas of '
     'our institution"',
     'Global confirmed.', 'no'),
    ('/data-innovation-office', 'Home > Data Innovation Office. Offices in Karachi and '
     'Nairobi. Nav: About Us, Research, Partnerships, Events',
     'University-wide across two countries. Global confirmed.', 'no'),
    ('/procurement', 'Home > Procurement. Run by the Purchasing & Supply Chain '
     'Management Division, procuring for the whole university from Karachi',
     'Global confirmed, no longer inferred.', 'yes'),
    ('/emeritus-prof', 'Home > Emeritus Professor. Governed by the University '
     'Appointments and Promotions Committee; emeriti in Pakistan, East Africa and London',
     'Global confirmed.', 'no'),
    ('/founders-day', 'Home > Founder’s Day. The first was 16 March 2023, AKU’s 40th '
     'anniversary',
     'Global confirmed, no longer inferred.', 'yes'),
    ('/sdg-hub', 'Home > Sustainable Development Goals Information Hub. No owning unit '
     'named on the page',
     'Global confirmed; nobody is named as its owner.', 'no'),

    # --- projects and campaigns, several of them dated ---------------------
    ('/vrw', 'Home > Voices from the Roof of the World. Covers Kyrgyzstan, Nepal, '
     'Pakistan and Tajikistan, with the Aga Khan Agency for Habitat, the Aga Khan '
     'Foundation and the University of Central Asia. Nav: Season 1, 2, 3, Film Selection',
     'A four-country initiative, not a Pakistan project — moved to global. Second '
     'sighting of Central Asia, and the first of Nepal, Kyrgyzstan and Tajikistan.', 'yes'),
    ('/tele-icu', 'Home > Tele-ICU Project. 24/7 remote ICU support, Pakistani phone '
     'number, support.teleicu@aku.edu',
     'Pakistan confirmed, no longer inferred.', 'yes'),
    ('/ek-saath', 'Home > Ek Saath. Rare inherited metabolic disorders, with '
     'Pak-IMD-Net and the Pakistan Society of Chemical Pathologists',
     'Pakistan confirmed, no longer inferred.', 'yes'),
    ('/wed', 'Home > OneAKU for OneEarth. The World Environment Day 2022 campaign, '
     'run by AKU’s Environment and Sustainability unit (environment@aku.edu)',
     'Belongs beside global/about/environment, and it is a dated 2022 campaign.', 'yes'),
    ('/covid-mental-health-response', 'Home > COVID-19 Mental Health Response. Child '
     'and adolescent mental health, with the British Asian Trust and others; language '
     'refers to "the ending of the lockdown"',
     'Global but dated — a pandemic-era campaign, an archive candidate.', 'yes'),
    ('/sonam-strategy', 'Home > School of Nursing & Midwifery Strategic Planning. '
     'Covers SONAM in Pakistan AND East Africa — four countries. Countdown expired '
     '30 June 2021 on a six-month project begun December 2020',
     'Not a Pakistan-only division, and finished years ago.', 'yes'),

    # --- the remaining ambiguous ones --------------------------------------
    ('/govprogramme', 'Home > Governance Programme. "run by the Institute for the '
     'Study of Muslim Civilisations (ISMC) … based in London, United Kingdom at the '
     'Aga Khan Centre"',
     'Resolved: ISMC in the UK, not a GSMC department in Kenya. Closes an open question.', 'yes'),
    ('/mca', 'Home > Muslim Civilisations Abstract Project. No institute named on the page',
     'Nothing contradicts the ISMC placement, which rests on the CW/CA MCA groups.', 'no'),
    ('/cru', 'Home > Clinical Research Unit, Kenya. Nairobi. "a core facility of the '
     'Aga Khan University Cancer Centre — Experimental Therapeutics program"',
     'Kenya confirmed. Note it reports into a Cancer Centre programme.', 'no'),
    ('/uc-nbi', 'Home > University Centre, Nairobi. A 37,500 sq m building at 3rd '
     'Parklands Avenue that "houses our academic units"',
     'A building, not an academic unit — correctly not an entity.', 'no'),
    ('/sonamug', 'Home > School of Nursing and Midwifery, Uganda. A full section: 3 '
     'programmes, 250+ students, 1,400+ alumni, news into 2025-2026',
     'Live and substantial, yet it contributes ZERO pages to AKU’s migrate list — the '
     'page list may be missing this section entirely.', 'yes'),

    # --- third sweep: one level down, where department vs programme is decided
    ('/mcea/departments', 'Home > Medical College, East Africa > Departments. Publishes '
     '11 departments at Nairobi (Anesthesiology, Biomedical Sciences, Family Medicine, '
     'Haematology-Oncology, Internal Medicine, Obs & Gynae, Paediatrics, Pathology, '
     'Population Health, Radiology, Surgery) and 5 at Dar es Salaam',
     'The authoritative MC East Africa department list, and it splits by campus.', 'yes'),
    ('/mcea/medicine', 'Home > Medical College, East Africa > Medicine. "the largest '
     'department at Aga Khan University Hospital, Nairobi"',
     'A clinical department — promoted from plain folder.', 'yes'),
    ('/mcea/radiology', 'Home > Medical College, East Africa > Radiology. Listed among '
     'the clinical departments',
     'A clinical department — promoted from plain folder.', 'yes'),
    ('/mcea/pathology', 'Home > … > Pathology. Diagnostic services and a residency '
     'programme, Nairobi',
     'Department confirmed.', 'no'),
    ('/mcea/pgme', 'Home > … > Postgraduate Medical Education. "PGME programmes in nine '
     'areas of specialisation", Nairobi and Dar es Salaam',
     'A programme, not a department — demoted.', 'yes'),
    ('/mcpk/fellowship', 'Home > Medical College, Pakistan > Fellowships. "build on the '
     'strengths of the residency programmes", listed under Programmes',
     'A training programme, not a department — demoted.', 'yes'),
    ('/mcpk/residency', 'Home > … > Residency. Postgraduate clinical training, '
     '"distinct from the departments listed in the navigation"',
     'A training programme, not a department — demoted.', 'yes'),
    ('/mcpk/data-science', 'Home > … > Health Data Science. "the first Health Data '
     'Science Centre", established December 2020 under CITRIC',
     'A centre under CITRIC, not a department — demoted.', 'yes'),
    ('/mcpk/pathology', 'Home > … > Department of Pathology & Laboratory Medicine. '
     'Clinical labs, Karachi',
     'Department confirmed.', 'no'),
    ('/mcpk/paeds', 'Home > … > Department of Paediatrics & Child Health. Clinical '
     'services to age 18, Karachi',
     'Department confirmed.', 'no'),
    ('/mcpk/chs', 'Home > … > Department of Community Health Sciences. Academic rather '
     'than direct clinical care',
     'Department confirmed — academic, not clinical.', 'no'),
    ('/mcpk/ded', 'Home > … > Department for Educational Development',
     'Department confirmed.', 'no'),
    ('/mcpk/research', 'Home > … > Research. A functional division parallel to '
     'Programmes, Faculty and Departments',
     'A faculty function, correctly a plain folder rather than a department.', 'no'),
    ('/about/officers', 'Home > About AKU > Deans & Officers. The Provost, Vice '
     'Presidents, deans and centre directors across all campuses',
     'A university-wide leadership listing. Global confirmed.', 'no'),
    ('/about/environment', 'Home > About AKU > Environment & Sustainability. '
     '"involves every area of university life", all campuses',
     'University-wide — and where the OneAKU for OneEarth campaign belongs.', 'no'),
    ('/library/pk', 'Home > Library > Pakistan. Four libraries in Karachi, one in '
     'Gilgit, one in Chitral',
     'A region grouping page inside the Library function.', 'no'),
    ('/library/ea', 'Home > Library > East Africa. Nairobi (AKU Library), Dar es Salaam '
     '(FHS and IED), Kampala (FHS)',
     'A region grouping page; its leaves belong to named faculties.', 'no'),
    ('/library/ulo', 'Home > Library > University Librarian’s Office. Established 2008, '
     'manages libraries "throughout the University’s international campuses"',
     'University-wide. Global confirmed.', 'no'),
    ('/students/clubs-societies', 'Home > Students > Student Clubs & Societies. Splits '
     'ke / pk / tz / ug',
     'Confirms the country level inside a global function.', 'no'),
    ('/students/wellness', 'Home > Students > Counselling Services & Wellness. Run by '
     'the Counselling and Wellness Office (wellness.counsel@aku.edu); splits by four '
     'countries',
     'A named university-wide office behind a country-split function.', 'no'),
    ('/supportus/ways-to-give', 'Home > Support Us > Ways to Give',
     'Global confirmed.', 'no'),
    ('/geo/gmp', 'Home > Global Engagement Office > Global Mobility Programmes. '
     'Internships with AKDN agencies in 30+ countries, run from Karachi',
     'A GEO programme, correctly a folder under global/geo.', 'no'),
    ('/qtl/resources', 'Home > Network of Quality, Teaching and Learning > Resources. '
     'Frameworks, policies and tools the QTL_net authored',
     'A network resource library, correctly a folder.', 'no'),
    ('/cime/programmes', 'Home > Centre for Innovation in Medical Education > '
     'Programmes. Separate Events & Courses for Pakistan and East Africa',
     'Confirms CIME spans two regions.', 'no'),
    ('/sonampk/programmes', 'Home > School of Nursing & Midwifery, Pakistan > '
     'Programmes. BScN, Post-RN BScN, Post-RM BScM, MScN, PhD',
     'A programmes index by degree level.', 'no'),
    ('/ismc/people', 'Home > Institute for the Study of Muslim Civilisations > People. '
     'Staff and faculty directory, London',
     'Confirms ISMC is London.', 'no'),
    ('/crm/people', 'Home > Centre for Regenerative Medicine > People. Pakistan',
     'Confirms CRM is Pakistan.', 'no'),
    ('/mrtc-pk/research', 'Home > Mother & Child Health Research & Training Centre, '
     'Matiari > Research. A decade of population-based surveillance; no faculty named',
     'Matiari, Pakistan. No parent faculty stated, so it stays a region folder.', 'no'),
    ('/bmi/about', 'HTTP 404 at Pages/home.aspx',
     'The folder holds pages under other names; not a structural problem.', 'no'),
    ('/sonampk/about', 'HTTP 404 at Pages/home.aspx',
     'Same — the landing page uses a different file name.', 'no'),

    # --- fourth sweep: thin folders, and the programme / centre distinction --
    ('/iedpk/med', 'Home > Institute for Educational Development, Pakistan > Master of '
     'Education. "This is a degree programme, not a department"',
     'A degree programme — demoted from department.', 'yes'),
    ('/iedpk/mphil', 'Home > … > MPhil in Education. "Master of Philosophy in Education"',
     'A degree programme — demoted from department.', 'yes'),
    ('/iedpk/phd', 'Home > … > PhD in Education. "Doctor of Philosophy in Education"',
     'A degree programme — demoted from department.', 'yes'),
    ('/iedpk/adv-diploma', 'Advanced Diploma in Education. "currently under review and '
     'is not offering admissions"',
     'A degree programme, and an inactive one — demoted, and an archive candidate.', 'yes'),
    ('/iedpk/cpe', 'Home > … > Continuing Education. "Continuing Professional Education"',
     'A programme, not a department.', 'yes'),
    ('/iedpk/pdc-karachi', 'Home > … > Professional Development Centre, Karachi. '
     '"functions as a specialized unit within the Institute"',
     'A CENTRE — a third kind, which IED’s own nav gives its own menu item.', 'yes'),
    ('/iedpk/pdc-north', 'Home > … > Professional Development Centre, North. '
     '"an extended arm of AKU-IED … in the Gilgit-Baltistan (GB) region"',
     'A centre, in Gilgit-Baltistan.', 'yes'),
    ('/iedpk/outreach', 'Home > … > Outreach. Delivered through the Professional '
     'Development Centres in Gilgit, Chitral and Karachi',
     'A function of IED, delivered through its centres.', 'no'),
    ('/iedpk/edip', 'Educational Development and Improvement Programme (EDIP). '
     'End date 2015',
     'A programme that finished in 2015 — an archive candidate.', 'yes'),
    ('/mcpk/cgsc', 'Home > Medical College, Pakistan > Centre of Global Surgical Care',
     'A centre under the Medical College, not a department.', 'yes'),
    ('/mcpk/dcpe', 'Home > … > Department of Continuing Professional Education',
     'A department, in its own words — kept.', 'no'),
    ('/mcpk/chs/educational-programmes', 'Home > … > Department of Community Health '
     'Sciences > Educational Programmes. Five MSc/MS degrees, a residency and a PhD stream',
     'Departments hold programmes beneath them — the levels nest, they are not rivals.', 'no'),
    ('/mcea/faculty', 'Home > Medical College, East Africa > Faculty. A directory '
     'covering the East Africa departments',
     'A function, correctly a folder.', 'no'),
    ('/ismc/abbasid-identities', 'Institute for the Study of Muslim Civilisations > '
     'Abbasid Identities. A Gerda Henkel Foundation research project ending June 2026',
     'A research project — a fourth kind, neither department, programme nor centre.', 'yes'),
    ('/ismc/research/fellowships', 'Home > ISMC > Research > Fellowships. Visiting '
     'fellowships at the Aga Khan Centre in London’s Knowledge Quarter',
     'A programme of ISMC. Confirms London again.', 'no'),
    ('/ctu/services', 'Home > Clinical Trials Unit > Our Services. Protocol development, '
     'ethics submission, monitoring, archiving',
     'A services page. Pakistan.', 'no'),
    ('/cime/technology', 'Home > Centre for Innovation in Medical Education > '
     'Technology. Separate simulator and venue sections for Pakistan and East Africa',
     'Reinforces CIME spanning two regions.', 'no'),
    ('/bmi/engagement', 'Home > Brain & Mind Institute > Engagement. Partnerships with '
     'academia, government, funders and business',
     'A function, correctly a folder.', 'no'),
    ('/ihd/projects', 'Home > Institute for Human Development > Projects. Early '
     'Childhood Development, Women Empowerment, Climate Change and Health, Mental '
     'Health, Neurodevelopment Disorders',
     'Named project areas; no countries stated on the page.', 'no'),
    ('/faspk/about', 'Home > Faculty of Arts and Sciences, Pakistan > About Us. '
     '"welcome its inaugural class of up to 100 students"',
     'FAS Pakistan is new — its inaugural undergraduate class. Explains the thin folders.', 'yes'),

    # --- fifth sweep: the 44 event microsites ------------------------------
    # Each has a SharePoint group named after the event itself, which says nothing
    # about the faculty behind it. Their own pages do. Owners and dates are held in
    # event_owners.py; the entries below are the ones that changed something.
    ('/events/aasc', 'Home > Events > Annual Surgical Conference. "Department of '
     'Surgery at AKU Medical College, Karachi". 11th edition, 1-2 April 2026',
     'Belongs to MC Pakistan / Surgery. Active.', 'yes'),
    ('/events/africme', 'Home > Events > Africa Regional Congress of ICMI. Hosted by '
     'AKU IED East Africa in Dar es Salaam. AFRICME 5, August 2018',
     'Belongs to IED East Africa. Last ran 2018 — archive candidate.', 'yes'),
    ('/events/apn', 'Home > Events > Advanced Practice Nursing. "Schools of Nursing '
     'and Midwifery, Pakistan and East Africa". November 2020',
     'Jointly owned by BOTH SONAM schools. Last ran 2020.', 'yes'),
    ('/events/icehd', 'International Conference on Early Human Development. Institute '
     'for Human Development jointly with COE-WCH, Karachi',
     'Two entities jointly — the clearest case for tags over folders.', 'yes'),
    ('/events/mental-health', 'Regional Conference on Mental Health. Institute for '
     'Human Development AND SONAM East Africa',
     'Two entities jointly, East Africa.', 'yes'),
    ('/events/5uc', '2nd Five University Consortium Scientific Conference. Hosted by '
     'the Arusha Climate & Environmental Research Centre, Morogoro, Tanzania',
     'Belongs to ACER — nothing in the permissions said so.', 'yes'),
    ('/events/chs-conference', 'International Conference — Healthy Futures. Department '
     'of Community Health Sciences, Pakistan. 7-8 June 2024',
     'Belongs to MC Pakistan / Community Health Sciences. Active.', 'yes'),
    ('/events/phc-sym', 'Public Healthcare Symposium. Department of Community Health '
     'Sciences, Karachi. 15-16 April 2025',
     'Same department. Active.', 'yes'),
    ('/events/mycology-conference', 'Mycology Conference. Department of Pathology & '
     'Laboratory Medicine, Karachi. 4-5 December 2017',
     'Belongs to MC Pakistan / Pathology. Last ran 2017 — archive candidate.', 'yes'),
    ('/events/sotl', 'Scholarship of Teaching and Learning Conference. Run by QTL_net '
     'from Karachi. 5th biennial, 2023',
     'Belongs to the QTL network. Last ran 2023.', 'yes'),
    ('/events/nhsrs', 'National Health Science Research Symposium. Faculty of Health '
     'Sciences, Pakistan. 26th edition, 31 Jan - 1 Feb 2025',
     'Active.', 'yes'),
    ('/events/isrc', 'International Student Research Conference. Student Research '
     'Forum, Karachi. 22-23 August 2026',
     'Active.', 'yes'),
    ('/events/elimu', 'Annual Regional Conference. Aga Khan University, Dar es Salaam. '
     '19-21 August 2026',
     'Active, East Africa.', 'yes'),
    ('/events/aechrs', "Annual Early-Career Health Researchers' Symposium. AKU Research "
     'Office, Kenya. 20-21 November 2026',
     'Active, Kenya.', 'yes'),
    ('/events/knec', 'The Kenya National Education Conference. AKU IED East Africa, '
     'Nairobi. 15-17 April 2019',
     'IED East Africa, in Kenya. Last ran 2019 — archive candidate.', 'yes'),
    ('/events/ari', 'Annual Research Institute. AKU IED East Africa, Tanzania. 7th, '
     '4-6 December 2019',
     'IED East Africa. Last ran 2019 — archive candidate.', 'yes'),
    ('/events/hsra', 'Health Sciences Research Assembly. AKU Health Sciences faculties. '
     '14th, 28 Feb - 2 Mar 2023',
     'University-wide. Last ran 2023.', 'yes'),
    ('/events/icnm', 'International Conference for Nurses and Midwives. AKU-SONAM, '
     'Pakistan. 2016',
     'SONAM Pakistan. Last ran 2016 — archive candidate.', 'yes'),
    ('/events/research-conference', "Nursing SPIRIT '24 — Students' Perspectives in "
     'Research & Innovation Trends. AKU-SONAM Pakistan, 2024',
     'SONAM Pakistan. Active.', 'yes'),
    ('/events/parwaaz', 'Parwaaz — AKU Congress of Student Experience. Office of the '
     'Dean of Students, Karachi. 23-25 November 2018',
     'Last ran 2018 — archive candidate.', 'yes'),
    ('/events/inter-professional-conf', 'The Health Care Quality Challenge Conference '
     '2016. AKU with AKDN and the Johnson & Johnson Trust, Nairobi',
     'Kenya. Last ran 2016 — archive candidate.', 'yes'),
    ('/events/dtea', 'Digital Transformation in East Africa. 17-18 April 2024',
     'East Africa. Active.', 'yes'),
    ('/events/src', 'Student Research Conference. National Student Research Conference '
     '2020',
     'Last ran 2020 — archive candidate.', 'yes'),
    ('/events/sports-olympiad', 'Sports Olympiad, Stadium Road Karachi. 21-28 February '
     '2020',
     'Last ran 2020 — archive candidate.', 'yes'),

    # --- sixth sweep: the remaining home pages, and the lists that settle them
    ('/research/centres', 'Research Centres. Names Centre for Regenerative Medicine, '
     'COE-WCH, Brain and Mind Institute, IGHD, and ISMC (London, since 2002), plus '
     'Clinical Research Unit Kenya and Clinical Trials Unit Pakistan',
     'Confirms CRM as a published research centre — it is rightly an entity.', 'no'),
    ('/research/facilities', 'Core Facilities. Names Animal House, Juma Research '
     'Laboratory, Clinical Trials Unit, Clinical Research Unit, Pathology Core, '
     'Imaging Core and the DIGITAL HEALTH RESOURCE CENTRE',
     'DHRC is a published AKU core facility — promoted from region folder to entity. '
     'The Cancer Centre appears nowhere on this list.', 'yes'),
    ('/research/themes', 'Research themes: Health & Medicine, Education, Muslim '
     'Cultures, Media & Communications. Neither Cancer Centre nor DHRC named',
     'The four research themes; a possible tag vocabulary.', 'no'),
    ('/research/oric', 'Home > Research > Office of Research, Innovation and '
     'Commercialisation. Central research office since 1999',
     'University-wide. Global confirmed.', 'no'),
    ('/about/at-a-glance', 'Repeats the six Global Institutes & Centres, the five '
     'campuses, and CRU Kenya / CTU Pakistan',
     'Fourth independent confirmation of the global-institutes list.', 'no'),
    ('/mrtc-pk', 'Home > Mother & Child Health Research & Training Centre, Matiari. '
     '"operates under The Division of Women and Child Health and Community Health '
     'Sciences at Aga Khan University". Matiari, Sindh, Pakistan',
     'A research centre INSIDE Medical College Pakistan, not a standalone unit under '
     'the region — moved in.', 'yes'),
    ('/digital-flipbooks', 'Home > Human Resources Communications Digital Flipbooks. '
     'Run by Human Resources Communications',
     'An HR function. Global confirmed.', 'no'),

    # --- seventh sweep: the 5-to-9 page band ------------------------------
    ('/mcpk/allied-health', 'Home > Medical College, Pakistan > Office of Allied '
     'Health. "The Office of Allied Health [OAH], Medical College was conceptualized '
     'in 2021"',
     'An OFFICE — a fifth kind, neither department nor programme. Demoted from department.', 'yes'),
    ('/mcpk/ccbp', 'Home > … > Centre for Clinical Best Practices. "Center for '
     'Clinical Best Practices (CCBP)"',
     'A centre — demoted from department.', 'yes'),
    ('/mcpk/cbcb', 'Home > … > Centre for Bioinformatics and Computational Biology',
     'A centre — promoted from plain folder.', 'yes'),
    ('/library/ulo/copyright', 'Home > Library > University Librarian’s Office > '
     'Copyright Office. "the main point of contact for copyright matters"',
     'An office inside an office. Confirms the kind exists outside faculties too.', 'yes'),
    ('/mcpk/undergraduate', 'Home > … > Undergraduate. "Undergraduate Programmes" — '
     'MBBS and Associate of Science in Dental Hygiene',
     'A programme, not a department.', 'yes'),
    ('/iedpk/step', 'Home > … > Strengthening Teacher Education in Pakistan. A project, '
     '2009 to 2016, funded by Global Affairs Canada and Aga Khan Foundation Canada',
     'A finished project — archive candidate, not a migration.', 'yes'),
    ('/mcpk/digital-magazine', 'Home > … > Digital Magazine. Produced by MC Pakistan; '
     'most recent content refers to 2020',
     'A publication, and a stale one.', 'yes'),
    ('/careers/aspire', 'Home > Careers > Aspire Programme. "Aspire Future Leaders '
     'Programme", open for Pakistan, East Africa "Stay tuned"',
     'A programme under Careers; East Africa not launched yet.', 'no'),
    ('/supportus/iss', 'Home > Support Us > Inspiring Student Success. Donor-supported '
     'student stories',
     'A fundraising campaign under Support Us.', 'no'),
    ('/mcea/surgery', 'Home > Medical College, East Africa > Surgery. "one of the '
     'leading surgical teaching institutes in East and Central Africa", Nairobi, with '
     'Tanzania references',
     'Department confirmed, and it spans both East Africa campuses.', 'no'),
    ('/mcpk/ophthalmology', 'Home > … > Department of Ophthalmology & Visual Sciences',
     'Department confirmed.', 'no'),
    ('/cime/facilities', 'Home > CIME > Facilities. Simulators and bookable venues in '
     'both Pakistan and East Africa',
     'Reinforces CIME operating in two regions.', 'no'),
    ('/ismc/study', 'Home > ISMC > Study. MA in Muslim Cultures, PhDs, Short Courses, '
     'the Aga Khan Library. Victoria Hall, King’s Cross, Central London',
     'ISMC’s programme set, and London again.', 'no'),
    ('/iedea/academics', 'Home > IED East Africa > Academic Programmes. Master of '
     'Education with six specialisations, plus a Centre for Continuing Education & '
     'Lifelong Learning. Dar es Salaam',
     'Another centre named — IED East Africa has one too.', 'yes'),
    ('/cancer-centre/information-hub', 'HTTP 401',
     'The whole Cancer Centre tree is private, not just its landing page.', 'yes'),
    ('/mcpk/pathology/labrad', 'Home > Medical College, Pakistan > Department of '
     'Pathology & Laboratory Medicine > LABRAD. "Newsletter of the Departments of '
     'Pathology & Laboratory Medicine and Radiology", Volume 50 Issue 1',
     'A publication, not a unit — and issued by two departments jointly, so it '
     'is the sixth kind: publication.', 'yes'),
    ('/careers/ovp', 'Home > Careers > Overseas Volunteer Professionals. '
     'Professionals abroad request a placement; HR matches them to a department',
     'A recruitment route run by HR, open to every campus — global, and the '
     'countries come off the page rather than off an entity.', 'yes'),
    ('/bmi/education', 'Home > Brain & Mind Institute > Education. Thirteen '
     'training programmes, not degrees. "9 Countries, 15 Cities, 4 Languages"',
     'Confirms BMI as global and gives its reach in its own numbers.', 'yes'),
    ('/alumni/aerf', 'Home > Alumni > Lifetime Alumni Email Account. "their own AKU '
     'alumni email addresses to serve as a lifetime link to the alma mater"',
     'A service under Alumni Affairs, not a fund — the slug misleads.', 'no'),
    ('/iedea/dev-projects', 'Home > IED East Africa > Development Projects. Ongoing: '
     'F4L, a tech-supported teacher-PD study in Tanzania. Completed: SESEA, Fursa '
     'kwa Watoto, STRAPPS, SOS Play and Learn, Uganda head-teacher training',
     'AKU marks ongoing and completed itself, and the work spans all three East '
     'African countries.', 'yes'),
    ('/ismc/publications', 'Home > ISMC > Publications. Seven series: In '
     'Translation, the Abdou Filali-Ansary Occasional Papers, Independent Volumes, '
     'the Journal of Material Cultures in the Muslim World, Exploring Muslim '
     'Contexts, Music and Performance, Muslim Civilisations Abstracts',
     'A function folder listing series, not a publication in itself — stays a '
     'folder.', 'no'),
    ('/mcpk/pathology/research-day', 'Home > Medical College, Pakistan > Department '
     'of Pathology & Laboratory Medicine > Research Day. Abstract books for 2021 '
     'and 2020, nothing later',
     'Dated content outside /events — which nothing could flag before, so '
     'archive candidacy now works anywhere in the tree.', 'yes'),
    ('/ighd/what-we-do', 'Home > IGHD > What We Do. Solutions for "low- and '
     'middle-income countries", disaster, conflict and health emergencies',
     'No home country claimed — confirms global.', 'no'),
    ('/ele-net/services', 'Home > Network of English Language Enhancement > '
     'Services. Individual consultancy, bespoke courses, British Council Aptis '
     'testing',
     'A service network for all of AKU — confirms global.', 'no'),
    ('/GNV/projects', 'Home > Giving Nature a Voice > Projects. Four seasons of 13 '
     'episodes from 2016; the fourth is "this dramatic final season". Teams from '
     'Kenya, Uganda, Tanzania, Rwanda, Burundi and DR Congo',
     'A concluded documentary series under GSMC, working across six countries.',
     'yes'),
    ('/coe-wch/impact', 'Home > Centre of Excellence in Women and Child Health. '
     'Impact split into South & Central Asia (Pakistan) and East Africa',
     'Confirms one centre with regional arms rather than two entities.', 'no'),
    ('/students/accomodations', 'Home > Students > Accomodations. Separate sections '
     'for Pakistan, Kenya, Uganda and Tanzania; no office named',
     'Country is a leaf under a global function, not a region parent.', 'no'),
    ('/supportus/where-to-give', 'Home > Support Us > Where to Give. Two routes: '
     'The Annual Fund and Capital Gifts',
     'Giving splits by instrument, not by campus — so it stays one global '
     'folder.', 'no'),
    ('/crm/facilities', 'Home > Centre for Regenerative Medicine > Facilities. FACS '
     'Core, Imaging Core, Pathology Core, Tissue Culture, "first floor of Juma '
     'Building at the AKU, Karachi Campus"',
     'Four fee-based core facilities in one building — Pakistan, and folders '
     'rather than centres.', 'yes'),
    ('/library/pk/ied-gilgit', '"IED Professional Development Centre, '
     'Gilgit-Baltistan Library" — run by the Library on IED’s PDC campus',
     'Confirms the branch-library rule: the Library owns it, IED is tagged '
     'alongside.', 'no'),
    ('/students/clubs-societies/ug', 'Home > Students > Student Clubs & Societies > '
     'Uganda', 'Country last in the trail, same as the three Pakistan ones.', 'no'),
    ('/students/health/pk', 'Home > Students > Physical Health > Pakistan',
     'Country last again — four consistent trails settle it.', 'no'),
    ('/students/experience/pk', 'Home > Students > Student Experience > Pakistan',
     'Same shape.', 'no'),
    ('/students/wellness/pk/mental-healthcare', 'Home > Students > Counselling '
     'Services & Wellness > Pakistan > Mental Health Care. Delivered by the Student '
     'Counselling and Wellness office',
     'Country sits mid-trail with a topic beneath it — still a leaf variant, '
     'not a region.', 'no'),
    ('/qtl/about', 'Home > Network of Quality, Teaching and Learning. No campus or '
     'country claimed anywhere on the page',
     'Confirms QTL_net as a global network.', 'no'),
    ('/cete/about/team', 'Home > Centre of Excellence for Trauma & Emergencies > '
     'About Us > Meet the Team > Leadership. Pakistan admissions, the Pakistan Life '
     'Savers Programme',
     'Confirms CETE’s full name and Pakistan.', 'no'),
    ('/mcea/about', 'Home > Medical College, East Africa > About Us. "134 faculty '
     'on two campuses (Kenya and Tanzania)", a Mombasa research facility, and a '
     'planned Kampala campus and hospital',
     'One college, not one per country — confirms east-africa with Uganda '
     'still to come.', 'no'),
    ('/mcpk/sig', 'Home > Medical College, Pakistan > Surgery Interest Group. "A '
     'student led body for mentoring & motivating aspiring surgeons via a platform '
     'to interact with surgical alumni and practicing surgeons"',
     'A student society, not a department — and the largest thing still '
     'mis-typed, at 23 pages.', 'yes'),
    ('/mcpk/patient-safety', 'Home > Medical College, Pakistan > Centre for Patient '
     'Safety — the page heading says the same',
     'A centre, not a department.', 'yes'),
    ('/mcpk/hdp', 'Home > Medical College, Pakistan > Human Development Programme. '
     'Established 2003, child development across education, health, nutrition and '
     'early stimulation. AKU’s own Departments menu lists it alongside Medicine '
     'and Surgery, but every mention on the page calls it a programme',
     'AKU’s menu and AKU’s page disagree, so it goes to the decisions list '
     'rather than being guessed.', 'yes'),
    ('/crm/ethics', 'HTTP 401',
     'Another private CRM folder, and at 19 pages the third largest.', 'yes'),
    ('/mcpk/transform-lives', 'Home > Transform Lives. A fundraising campaign '
     'inviting donors to endow MBBS scholarships — USD 100,000 endowed or USD '
     '5,000 a year, enquiries to scholarships@aku.edu',
     'A campaign, not a department. Its owner group AF (Advancement) is a new '
     'owning unit, which is the whole reason it passed the department test.', 'yes'),
    ('/mcpk/bbs', 'Home > Medical College, Pakistan > Department of Biological & '
     'Biomedical Sciences — a 2001 merger of Anatomy, Biochemistry, Physiology '
     'and Pharmacology', 'A real department, confirmed.', 'no'),
    ('/mcpk/em', 'Home > Medical College, Pakistan > Department of Emergency '
     'Medicine', 'A real department, confirmed.', 'no'),
    ('/mcpk/surgery', 'Home > Medical College, Pakistan > Department of Surgery',
     'A real department, confirmed.', 'no'),
    ('/mcpk/psychiatry', 'Home > Medical College, Pakistan > Department of '
     'Psychiatry', 'A real department, confirmed.', 'no'),
    ('/mcpk/anaes', 'Home > Medical College, Pakistan > Department of '
     'Anaesthesiology', 'A real department, confirmed.', 'no'),
    ('/mcpk/obs-gyn', 'Home > Medical College, Pakistan > Department of Obstetrics & '
     'Gynaecology', 'A real department, confirmed.', 'no'),
    ('/mcpk/fam-med', 'Home > Medical College, Pakistan > Department of Family '
     'Medicine — "named a separate department in 2003", previously part of CHS',
     'A real department, confirmed.', 'no'),
    ('/mcpk/radiology', 'Home > Medical College, Pakistan > Department of Radiology',
     'A real department, confirmed — the last of the 23.', 'no'),
    ('/mcpk/med', 'Home > Medical College, Pakistan > Department of Medicine. A '
     'clinical department with specialty areas and training programmes',
     'The Department of Medicine, not a degree. Its owner group is called "Dept '
     'of Medicine". It read as a folder because `med` was excluded university-wide '
     'for IED, where it means Master of Education — so the exclusion is now '
     'scoped per entity.', 'yes'),
    ('/mcpk/data-science', 'Home > Medical College, Pakistan > Health Data Science. '
     '"the first Health Data Science Centre under The Clinical and Translational '
     'Research Incubator (CITRIC)", inception December 2020',
     'A centre, which this repo’s own comment already said — the code '
     'just never acted on it.', 'yes'),
]

# Fetched and found not publicly reachable. Their pages are still in AKU's migrate
# list, so somebody has to decide: publish, migrate as private, or drop.
NOT_PUBLIC = [
    ('/cancer-centre', 401, 25, 'a named Pakistan unit on the Pakistan landing page'),
    ('/mcpk/bioinformatics', 401, 2, 'Centre for Bioinformatics'),
    ('/mcpk/coors', 401, 2, 'Centre of Oncological Research in Surgery'),
    ('/crm/programmes', 401, 1, 'Centre for Regenerative Medicine — Programmes'),
    ('/crm/ethics', 401, 19, 'Centre for Regenerative Medicine — Ethics'),
    ('/iedpk/transform-lives', 401, 3, 'IED Pakistan — Transform Lives'),
    ('/dhrc', 401, 13, 'Digital Health Resource Centre'),
    ('/vroom', 401, 0, 'Vroom'),
    ('/mcke', 401, 0, 'Medical College, Kenya — the empty stub'),
    ('/mctz', 401, 0, 'Medical College, Tanzania — the empty stub'),
    ('/iedtz', 401, 0, 'Institute for Educational Development, Tanzania — the empty stub'),
    ('/sonamke', 401, 0, 'School of Nursing and Midwifery, Kenya — the empty stub'),
    ('/sonamtz', 401, 0, 'School of Nursing and Midwifery, Tanzania — the empty stub'),
    ('/akuchallenge', 404, 0, 'AKU Challenge — gone from the live site'),
    ('/events/acc', 401, 0, 'Annual Cardiovascular Conference'),
    ('/events/whd', 401, 0, 'World Hepatitis Day'),
    ('/events/pls', 401, 0, 'Public Lecture Series'),
    ('/events/neuro-conf', 401, 0, 'Neuroscience Conference'),
    ('/events/pnos', 401, 0, 'Annual Pakistan Pediatric Neuro-oncology Symposium'),
    ('/events/rare-diseases-conf', 401, 0, 'Rare Diseases Conference'),
    ('/apply-online', 404, 0, 'Apply Online — gone from the live site'),
    ('/akupreuniversity', 404, 0, 'AKU PreUni — gone from the live site'),
    ('/cancer-centre/information-hub', 401, 8, 'Cancer Centre — Information Hub'),
]

# Still to open. Ordered by how much content sits behind each, because that is
# the order in which a wrong placement costs the most.
# Every section landing page has now been opened. What is left is judgement, not
# discovery: see NOT_PUBLIC below, the stale events in event_owners.py, and the two
# ownership-vs-presentation disagreements (/ccit and /mca).
REMAINING = []

# Not worth opening: staging copies and a search utility.
SKIP = ['/test', '/test-supportus', '/ismc2', '/leads1', '/leads2', '/search']

if __name__ == '__main__':
    out = paths.out('aku-site-visits.csv')
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['status', 'pages_behind_it', 'url', 'what_aku_showed',
                    'what_it_settled', 'changed_a_placement'])
        for path, showed, settled, changed in VISITED:
            w.writerow(['visited', '', 'https://www.aku.edu' + path, showed,
                        settled, changed])
        for n, path, label in REMAINING:
            w.writerow(['to visit', n, 'https://www.aku.edu' + path, label, '', ''])
        for path, code, pages, label in NOT_PUBLIC:
            w.writerow(['not public', pages, 'https://www.aku.edu' + path,
                        'HTTP %d' % code,
                        '%s — pages are in the migrate list but the section is not '
                        'reachable; AKU has to decide' % label, 'yes'])
        for path in SKIP:
            w.writerow(['skip', '', 'https://www.aku.edu' + path,
                        'staging copy or utility, not content', '', ''])
    changed = sum(1 for v in VISITED if v[3] == 'yes')
    print('visited %d · changed a placement %d · not public %d · still to visit %d · skip %d'
          % (len(VISITED), changed, len(NOT_PUBLIC), len(REMAINING), len(SKIP)))
    print('wrote', os.path.basename(out))
