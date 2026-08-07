"""The region / entity classification for every aku.edu section.

Single source of truth, imported by both build_hierarchy.py and
build_migration_plan.py.  Each row records the rule that produced the
placement; `confidence` is W only when the export itself proves it.
"""

W = 'witnessed'   # the CSV proves it
I = 'inferred'    # name/slug convention or AKU fact, no witness in the export
D = 'decide'      # genuinely unresolved, needs AKU to answer

REGIONS = [
    ('global',         'Global',          'GL', 'no faculty owns this: central comms / university-wide'),
    ('pakistan',       'Pakistan',        'PK', 'Karachi, Matiari, Chitral, Gilgit'),
    ('east-africa',    'East Africa',     'EA', 'the level AKU’s own entity names use — an entity called '
                                                '"…, East Africa" runs across Kenya, Tanzania and Uganda at once'),
    ('kenya',          'Kenya',           'KE', 'Nairobi — entities that name one country only'),
    ('tanzania',       'Tanzania',        'TZ', 'Dar es Salaam, Arusha — entities that name one country only'),
    ('uganda',         'Uganda',          'UG', 'Kampala — entities that name one country only'),
    ('united-kingdom', 'United Kingdom',  'UK', 'London'),
    ('afghanistan',    'Afghanistan',     'AF', 'Kabul'),
]

# Which countries an East-Africa-wide entity actually operates in, read off its
# own live page rather than guessed from a login-domain majority. Used as a tag,
# because one folder cannot sit in three countries.
ENTITY_COUNTRIES = {
    'mcea':    ('Kenya, Tanzania',
                'aku.edu/mcea names the "Nairobi and Dar es Salaam Campuses"'),
    'sonamea': ('Kenya, Uganda, Tanzania',
                'aku.edu/sonamea lists Nairobi, Kampala and Dar es Salaam addresses'),
    'iedea':   ('Tanzania, Kenya, Uganda',
                'aku.edu/iedea states "Based in Dar es Salaam, Tanzania"; serves all three'),
    'fasea':   ('Kenya, Tanzania, Uganda',
                'aku.edu/fasea is titled "…, East Africa" and names no single city'),
    # the Global Institutes & Centres, with the countries each names for itself
    'bmi':     ('Kenya, Pakistan',
                'aku.edu/bmi gives Nairobi as primary contact and Karachi second'),
    'ihd':     ('Kenya, Tanzania',
                'aku.edu/ihd gives a Nairobi address; its news covers Tanzania'),
    'ighd':    ('Pakistan',
                'aku.edu/ighd is Karachi-based, serving South and Central Asia and Africa'),
    'cime':    ('Pakistan, Kenya, Tanzania',
                'aku.edu/cime carries "Pakistan" and "East Africa" as left-nav siblings'),
    'coe-wch': ('Pakistan, Kenya, Tanzania, Uganda, Central Asia',
                'aku.edu/coe-wch is one centre with South & Central Asia and East Africa arms; '
                'its own folders are /pk, /ea and /ca'),
    'eai':     ('Kenya, Uganda, Tanzania, Rwanda',
                'aku.edu/eai speaks for all four and names no home city'),
}

# ---------------------------------------------------------------------------
# What counts as an entity, decided by AKU rather than by me.
#
# Two pages on aku.edu publish the answer:
#   /academics  lists the academic units, grouped by country
#   /research   lists "Global Institutes & Centres", plus the two clinical units
# Anything on either list is an entity and gets regions/{r}/entities/{slug}/.
# Anything not on either list is a real folder but not an entity, so it sits at
# region level -- regions/pakistan/cancer-centre/ -- which is also why a region
# needs to be able to hold plain folders.
ACADEMIC_UNITS = {          # from /academics, with the countries AKU lists
    'medical-college': 'Pakistan, Kenya, Tanzania',
    'school-of-nursing-and-midwifery': 'Pakistan, Kenya, Tanzania, Uganda',
    'institute-for-educational-development': 'Pakistan, Tanzania',
    'faculty-of-arts-and-sciences': 'Pakistan',
    'graduate-school-of-media-and-communications': 'Kenya',
    'institute-for-human-development': 'Kenya',
    'institute-for-the-study-of-muslim-civilisations': 'United Kingdom',
}
COUNTRY_UNITS = {           # named on a country landing page, e.g. aku.edu/pakistan
    'centre-for-regenerative-medicine': 'Pakistan',
    'centre-of-excellence-for-trauma-and-emergencies': 'Pakistan',
}
CORE_FACILITIES = {         # from /research/facilities, AKU's core facilities list
    'digital-health-resource-centre':
        'named as a core facility on aku.edu/research/facilities, alongside the '
        'Clinical Trials Unit, Clinical Research Unit, Pathology Core and Imaging '
        'Core. No country is given for it there, unlike "Clinical Trials Unit, '
        'Pakistan", but its editing groups are all Karachi',
}
INSTITUTES_CENTRES = {      # from /research -> Global Institutes & Centres
    'arusha-climate-and-environmental-research-centre': 'Global institute or centre',
    'brain-and-mind-institute': 'Global institute or centre',
    'centre-for-innovation-in-medical-education': 'Global institute or centre',
    'centre-of-excellence-in-women-and-child-health': 'Global institute or centre',
    'institute-for-global-health-and-development': 'Global institute or centre',
    'institute-for-human-development': 'Global institute or centre',
    'clinical-research-unit': 'Research unit, Kenya',
    'clinical-trials-unit': 'Research unit, Pakistan',
}

def entity_basis(slug):
    """Why this is (or is not) an entity. Returns (is_entity, reason)."""
    if slug in ACADEMIC_UNITS:
        return True, ('AKU lists it under Academics for %s'
                      % ACADEMIC_UNITS[slug])
    if slug in INSTITUTES_CENTRES:
        return True, ('AKU lists it under Research — %s'
                      % INSTITUTES_CENTRES[slug])
    if slug in COUNTRY_UNITS:
        return True, ('named as a unit on the aku.edu/%s landing page'
                      % COUNTRY_UNITS[slug].lower())
    if slug in CORE_FACILITIES:
        return True, CORE_FACILITIES[slug]
    return False, ('not named on aku.edu/academics or aku.edu/research, so it is '
                   'a folder at region level rather than an entity')

# section -> (region, entity slug or None, entity display, division under entity,
#             confidence, provenance)
# entity None => the section is a global function, not an entity.
SEC = {
 # ---- region landing pages -------------------------------------------------
 'pakistan':       ('pakistan', None, None, None, W, 'CSV title "Pakistan" — region landing page'),
 'kenya':          ('kenya', None, None, None, W, 'CSV title "Kenya" — region landing page'),
 'tanzania':       ('tanzania', None, None, None, W, 'CSV title "Tanzania" — region landing page'),
 'uganda':         ('uganda', None, None, None, W, 'CSV title "Uganda" — region landing page'),
 'united-kingdom': ('united-kingdom', None, None, None, W, 'CSV title "United Kingdom" — region landing page'),

 # ---- Pakistan entities ----------------------------------------------------
 'mcpk':    ('pakistan', 'medical-college', 'Medical College', None, W,
             'slug suffix pk + CSV "Medical College, Pakistan" + owner groups CW/CA MC PK, FacultyOwners-mcpk'),
 'iedpk':   ('pakistan', 'institute-for-educational-development', 'Institute for Educational Development', None, W,
             'slug suffix pk + CSV "…, Pakistan" + owner groups CW/CA IED PK'),
 'sonampk': ('pakistan', 'school-of-nursing-and-midwifery', 'School of Nursing and Midwifery', None, W,
             'slug suffix pk + CSV "…, Pakistan" + owner groups CW/CA SONAM PK'),
 'faspk':   ('pakistan', 'faculty-of-arts-and-sciences', 'Faculty of Arts and Sciences', None, W,
             'slug suffix pk + CSV "…, Pakistan" + owner groups CW/CA FAS PK, FAS-PK Faculty'),
 'mrtc-pk': ('pakistan', 'medical-college', 'Medical College',
             'mother-and-child-health-research-and-training-centre', W,
             'resolved on the live site: its own page states it "operates under The '
             'Division of Women and Child Health and Community Health Sciences", both '
             'Medical College Pakistan units — so it is a research centre inside the '
             'faculty, not a standalone unit under the region. Matiari, Sindh'),
 'cete':    ('pakistan', 'centre-of-excellence-for-trauma-and-emergencies', 'Centre of Excellence for Trauma & Emergencies', None, W,
             'owner groups CW/CA CETE; aku-domain majority 53 of 66 unique rows'),
 'crm':     ('pakistan', 'centre-for-regenerative-medicine', 'Centre for Regenerative Medicine', None, W,
             'owner groups CRM Writer / CRM Approver; Karachi stem-cell centre'),
 'cime':    ('global', 'centre-for-innovation-in-medical-education', 'Centre for Innovation in Medical Education', None, W,
             'aku.edu/research lists it under Global Institutes & Centres, and its own left nav '
             'carries "Pakistan" and "East Africa" as siblings — it splits by region internally'),
 'coe-wch': ('global', 'centre-of-excellence-in-women-and-child-health', 'Centre of Excellence in Women and Child Health', None, W,
             'aku.edu/research lists it under Global Institutes & Centres, and it carries its own '
             'coe-wch/pk, /ea and /ca (Central Asia) arms — one centre with regional arms'),
 'ctu':     ('pakistan', 'clinical-trials-unit', 'Clinical Trials Unit', None, W,
             'owner groups CW/CA CTU; aku 49 of 63 unique rows'),
 'dhrc':    ('pakistan', 'digital-health-resource-centre', 'Digital Health Resource Centre', None, W,
             'owner groups CW/CA DHRC; aku 44 of 57 unique rows'),
 'cancer-centre': ('pakistan', 'cancer-centre', 'Cancer Centre', None, W,
             'owner groups CW/CA Cancer Centre; aku 59 of 72 unique rows'),
 'bmi':     ('global', 'brain-and-mind-institute', 'Brain & Mind Institute', None, W,
             'aku.edu/research lists it under Global Institutes & Centres, and its own page gives '
             'Nairobi as the primary contact with Karachi second — cross-region, so global'),
 'ighd':    ('global', 'institute-for-global-health-and-development', 'Institute for Global Health & Development', None, W,
             'aku.edu/research lists it under Global Institutes & Centres; Karachi-based but '
             'serving South and Central Asia and Africa'),
 'ihd':     ('global', 'institute-for-human-development', 'Institute for Human Development', None, W,
             'aku.edu/research lists it under Global Institutes & Centres; its own page gives a '
             'Nairobi address, so the earlier Pakistan placement was wrong'),
 'tele-icu':  ('pakistan', 'tele-icu-project', 'Tele-ICU Project', None, W,
             'its own page gives a Pakistani phone number and support.teleicu@aku.edu — '
             'Pakistan confirmed on the live site'),
 'ek-saath':  ('pakistan', 'ek-saath', 'Ek Saath', None, W,
             'its own page names Pak-IMD-Net and the Pakistan Society of Chemical Pathologists '
             'as partners — a Pakistan initiative, confirmed'),
 'vrw':     ('global', 'voices-from-the-roof-of-the-world', 'Voices from the Roof of the World', None, W,
             'its own page covers Kyrgyzstan, Nepal, Pakistan and Tajikistan with the University '
             'of Central Asia — a four-country initiative, so global; the vrw/pk folder is one arm '
             'of it, not the whole thing'),
 'ccit':    ('pakistan', 'medical-college', 'Medical College', 'critical-creative-innovative-thinking', W,
             'owner groups CW/CA MC PK + FacultyOwners-mcpk alongside CW/CA CCIT — an MC Pakistan programme'),
 'sonam-strategy': ('global', 'school-of-nursing-and-midwifery', 'School of Nursing and Midwifery', 'strategic-planning', W,
             'its own page covers SONAM in Pakistan AND East Africa — Pakistan, Kenya, Tanzania '
             'and Uganda — so it is not a Pakistan-only division. Also dated: the project ran six '
             'months from December 2020 and its countdown expired on 30 June 2021'),

 # ---- East Africa entities (multi-country by AKU's own description) --------
 'mcea':    ('east-africa', 'medical-college', 'Medical College', None, W,
             'owner groups CW/CA MC EA, FacultyOwners-mcea; its own page names the '
             '"Nairobi and Dar es Salaam Campuses", so it is not a Kenya-only entity'),
 'sonamea': ('east-africa', 'school-of-nursing-and-midwifery', 'School of Nursing and Midwifery', None, W,
             'owner groups CW/CA SONAM EA, FacultyOwners-sea; its own page lists '
             'Nairobi, Kampala and Dar es Salaam addresses'),

 # ---- Kenya entities (one country named) ----------------------------------
 'gsmc':    ('kenya', 'graduate-school-of-media-and-communications', 'Graduate School of Media & Communications', None, W,
             'its own page gives the Nairobi address (University Centre, Third Parklands Ave) — '
             'confirmed against the live site, no longer inferred'),
 'eai':     ('east-africa', 'east-africa-institute', 'The East Africa Institute', None, W,
             'owner groups CW/CA EAI; its own page names no city and speaks for Kenya, Uganda, '
             'Tanzania and Rwanda — East Africa-wide, not Nairobi-only'),
 'cru':     ('kenya', 'clinical-research-unit', 'Clinical Research Unit', None, W,
             'CSV title says "Clinical Research Unit, Kenya"'),
 'uc-nbi':  ('kenya', 'university-centre-nairobi', 'University Centre, Nairobi', None, W,
             'CSV title names Nairobi'),
 'mcke':    ('kenya', 'medical-college', 'Medical College', 'mcke-stub', W,
             'CSV title "Medical College, Kenya" — empty stub, overlaps /mcea'),
 'sonamke': ('kenya', 'school-of-nursing-and-midwifery', 'School of Nursing and Midwifery', 'sonamke-stub', W,
             'CSV title "School of Nursing and Midwifery, Kenya" — empty stub, overlaps /sonamea'),
 'iedea':   ('east-africa', 'institute-for-educational-development', 'Institute for Educational Development', None, W,
             'owner groups CW/CA IED EA; resolved from its own page, which states '
             '"Based in Dar es Salaam, Tanzania" while serving Kenya and Uganda too — '
             'so East Africa, not the Nairobi majority the login domains suggested'),
 'GNV':     ('kenya', 'graduate-school-of-media-and-communications', 'Graduate School of Media & Communications', 'giving-nature-a-voice', W,
             'resolved on the live site: the GSMC left nav lists "Giving Nature a Voice" under its '
             'own Projects, so it is a GSMC project rather than a standalone campaign'),
 'govprogramme': ('united-kingdom', 'institute-for-the-study-of-muslim-civilisations', 'Institute for the Study of Muslim Civilisations', 'governance-programme', W,
             'resolved on the live site: its own page states the programme is run by ISMC at the '
             'Aga Khan Centre in London — not a GSMC department in Kenya as the taxonomy implied'),

 # ---- Tanzania entities ----------------------------------------------------
 'acer':    ('tanzania', 'arusha-climate-and-environmental-research-centre', 'Arusha Climate & Environmental Research Centre', None, W,
             'owner groups CW/CA AERR (AKU\u2019s own abbreviation, not a typo); CSV title names Arusha'),
 'iedtz':   ('tanzania', 'institute-for-educational-development', 'Institute for Educational Development', 'iedtz-stub', W,
             'CSV title "…, Tanzania" — empty stub'),
 'mctz':    ('tanzania', 'medical-college', 'Medical College', 'mctz-stub', W,
             'CSV title "Medical College, Tanzania" — empty stub'),
 'sonamtz': ('tanzania', 'school-of-nursing-and-midwifery', 'School of Nursing and Midwifery', 'sonamtz-stub', W,
             'CSV title "…, Tanzania" — empty stub'),
 'fasea':   ('east-africa', 'faculty-of-arts-and-sciences', 'Faculty of Arts and Sciences', None, W,
             'no owner group and no domain signal, but its own page is titled '
             '"Faculty of Arts and Sciences, East Africa" and names no single city — '
             'East Africa is the region it claims, so the earlier Arusha guess is dropped'),

 # ---- Uganda entities ------------------------------------------------------
 'sonamug': ('uganda', 'school-of-nursing-and-midwifery', 'School of Nursing and Midwifery', None, W,
             'CSV title "School of Nursing and Midwifery, Uganda"; 8 webs, no pages yet'),

 # ---- United Kingdom entities ---------------------------------------------
 'ismc':    ('united-kingdom', 'institute-for-the-study-of-muslim-civilisations', 'Institute for the Study of Muslim Civilisations', None, W,
             'owner groups CW/CA ISMC, FacultyOwners-ismc, ISMC Writer/Approver; the London ismc\\ directory supplies 20-25% of its unique rows against a 3% baseline elsewhere — a 7x enrichment, not a majority'),
 'mca':     ('united-kingdom', 'institute-for-the-study-of-muslim-civilisations', 'Institute for the Study of Muslim Civilisations', 'muslim-civilisations-abstract-project', W,
             'owner groups CW/CA MCA; an ISMC publication project'),

 # ---- global content hubs --------------------------------------------------
 'news':    ('global', None, None, None, W, 'CSV title "News" — the university news hub'),
 'events':  ('global', None, None, None, W, 'CSV title "Events"; 48 event microsites, each owned by an entity group'),
 'blogs':   ('global', None, None, None, W, 'CSV title "Blogs"; owner group BlogsOwner'),

 # ---- global functions ----------------------------------------------------
 'about':       ('global', None, None, None, W, 'owner groups CW/CA Public Affairs — central comms'),
 'academics':   ('global', None, None, None, W, 'owner groups Provost Office News Writer/Approver — university-wide'),
 'admissions':  ('global', None, None, None, W, 'owner groups CW/CA Registrar — university-wide'),
 'alumni':      ('global', None, None, None, W, 'owner groups CW/CA Alumni Affairs — university-wide'),
 'careers':     ('global', None, None, None, W, 'owner groups CW/CA HR — university-wide'),
 'vacancies':   ('global', None, None, None, W, 'owner groups CW/CA vacancies — HR'),
 'digital-flipbooks': ('global', None, None, None, W, 'owner groups CW/CA HR — HR comms'),
 'students':    ('global', None, None, None, W, 'owner group CW Students; Student Affairs routes to global'),
 'library':     ('global', None, None, None, W, 'owner groups CW/CA Library; its own pk/ ea/ split is kept inside'),
 'research':    ('global', None, None, None, W, 'owner groups CW/CA Research and Graduate Studies'),
 'supportus':   ('global', None, None, None, W, 'owner group CW Resource Development (see /test-supportus) — central fundraising'),
 'registrar':   ('global', None, None, None, W, 'owner groups CW/CA Registrar, CW/CA Registrar Office'),
 'convocation': ('global', None, None, None, W, 'owner groups CW/CA Convocation; already split global/ke/pk/tz/ug/uk inside'),
 'geo':         ('global', None, None, None, W, 'owner groups CW/CA Partnerships Office, CW/CA IIP'),
 'deib':        ('global', None, None, None, W, 'owner groups CW/CA DEI&B — university-wide'),
 'data-innovation-office': ('global', None, None, None, W, 'owner groups CW/CA Data Office; Data Office routes to global'),
 'procurement': ('global', None, None, None, W, 'its own page names the Purchasing & Supply Chain Management Division, procuring for the whole university from Karachi — confirmed'),
 'sdg-hub':     ('global', None, None, None, W, 'owner groups CW/CA Registrar — university-wide hub'),
 'emeritus-prof': ('global', None, None, None, W, 'owner groups CW/CA Emerita — university-wide'),
 'founders-day':  ('global', None, None, None, W, 'its own page describes the first Founder’s Day, 16 March 2023, for AKU’s 40th anniversary — university-wide, confirmed'),
 'wed':         ('global', None, None, None, W, 'its own page is the World Environment Day 2022 campaign, run by AKU’s Environment and Sustainability unit (environment@aku.edu) — so it belongs beside global/about/environment, and it is a dated campaign'),
 'covid-mental-health-response': ('global', None, None, None, W, 'its own page is a pandemic-era child and adolescent mental health response (camh@aku.edu) run with the British Asian Trust and others — university-wide but dated'),
 'akuchallenge':     ('global', None, None, None, W, 'own AKU Challenge Owners/Members/Visitors groups — university-wide'),
 'akupreuniversity': ('global', None, None, None, I, 'no permission rows at all beyond the root — inferred'),
 'apply-online':     ('global', None, None, None, I, 'no permission rows beyond the root; admissions utility — inferred'),
 'search':      ('global', None, None, None, W, 'search utility web, not editorial content'),
 'vroom':       ('global', None, None, None, W, 'owner groups CW/CA Vroom + ElectiveAdminGroup'),
 'leads':       ('global', None, None, None, W, 'owner groups CW/CA LEADS; lifelong-learning network, cross-region'),
 'qtl':         ('global', None, None, None, W, 'its own page states "The AKU-wide Network of Quality, Teaching and Learning was set up by the Provost in 2013" — university-wide, confirmed on the live site'),
 'ele-net':     ('global', None, None, None, W, 'its own page describes a university-wide network spanning Pakistan, East Africa, Uganda and the United Kingdom — confirmed on the live site'),

 # ---- not content: staging / duplicates ----------------------------------
 'test':           ('staging', None, None, None, W, 'CSV title "test"'),
 'test-supportus': ('staging', None, None, None, W, 'CSV title "Test-SupportUs" — a copy of /supportus'),
 'ismc2':          ('staging', None, None, None, W, 'duplicate of /ismc, no permission rows, no pages — unfinished rebuild'),
 'leads1':         ('staging', None, None, None, W, 'duplicate of /leads, no permission rows, no pages'),
 'leads2':         ('staging', None, None, None, W, 'duplicate of /leads (contains leads2/leads), no permission rows, no pages'),
}

