"""Who owns each event microsite, and when it last ran — read off its own page.

The 44 microsites under /events each have a SharePoint group named after the event
itself (`5UC`, `ACC`, `AECHRS`), which says nothing about which faculty runs it.
Their own pages do. So the entity tag for an event is witnessed here rather than
guessed from permissions.

The year matters as much as the owner: a conference whose last edition was 2016
is an archive candidate, not a page to carry forward. `latest` is the most recent
edition the page names.
"""

# slug -> (owning unit as the page names it, region, latest edition, notes)
EVENTS = {
    'aasc': ('Medical College Pakistan — Department of Surgery', 'pakistan', 2026,
             '11th Annual Surgical Conference, 1-2 April 2026'),
    'africme': ('Institute for Educational Development, East Africa', 'east-africa',
                2018, 'AFRICME 5, Dar es Salaam, 29-31 August 2018'),
    'apn': ('School of Nursing and Midwifery, Pakistan AND East Africa', 'global',
            2020, 'jointly run by both SONAM schools'),
    'hsra': ('Faculty of Health Sciences — university-wide', 'global', 2023,
             '14th assembly, 28 Feb - 2 Mar 2023'),
    'icnm': ('School of Nursing and Midwifery, Pakistan', 'pakistan', 2016,
             'last edition 2016'),
    'isrc': ('Student Research Forum, Karachi', 'pakistan', 2026,
             '22-23 August 2026'),
    'elimu': ('Aga Khan University, Dar es Salaam', 'east-africa', 2026,
              '19-21 August 2026'),
    'knec': ('Institute for Educational Development, East Africa', 'kenya', 2019,
             'Nairobi, 15-17 April 2019'),
    'nhsrs': ('Faculty of Health Sciences, Pakistan', 'pakistan', 2025,
              '26th edition, 31 Jan - 1 Feb 2025'),
    'sotl': ('Network of Quality, Teaching and Learning (QTL_net)', 'global', 2023,
             '5th biennial, Karachi'),
    'research-conference': ('School of Nursing and Midwifery, Pakistan', 'pakistan',
                            2024, "Nursing SPIRIT '24"),
    'parwaaz': ('Office of the Dean of Students, Karachi', 'pakistan', 2018,
                '23-25 November 2018'),
    'inter-professional-conf': ('Aga Khan University with AKDN and the Johnson & '
                                'Johnson Trust', 'kenya', 2016,
                                'Nairobi, 10-12 November 2016'),
    'chs-conference': ('Medical College Pakistan — Department of Community Health '
                       'Sciences', 'pakistan', 2024, '7-8 June 2024'),
    'mental-health': ('Institute for Human Development AND School of Nursing and '
                      'Midwifery, East Africa', 'east-africa', None,
                      'two entities jointly; no year on the page'),
    'dtea': ('Aga Khan University, East Africa', 'east-africa', 2024,
             '17-18 April 2024'),
    '5uc': ('Arusha Climate & Environmental Research Centre', 'tanzania', None,
            'held in Morogoro, Tanzania'),
    'ari': ('Institute for Educational Development, East Africa', 'east-africa',
            2019, '7th Annual Research Institute, 4-6 December 2019'),
    'aechrs': ('AKU Research Office, Kenya', 'kenya', 2026,
               '20-21 November 2026'),
    'phc-sym': ('Medical College Pakistan — Department of Community Health Sciences',
                'pakistan', 2025, 'Karachi, 15-16 April 2025'),
    'src': ('Aga Khan University', 'pakistan', 2020,
            'National Student Research Conference 2020'),
    'mycology-conference': ('Medical College Pakistan — Department of Pathology & '
                            'Laboratory Medicine', 'pakistan', 2017,
                            'Karachi, 4-5 December 2017'),
    'sports-olympiad': ('Aga Khan University, Karachi', 'pakistan', 2020,
                        '21-28 February 2020'),
    'icehd': ('Institute for Human Development AND Centre of Excellence in Women '
              'and Child Health', 'pakistan', None,
              'two entities jointly, hosted in Karachi'),
}

# Events whose own page shows no edition since this year are archive candidates
# rather than migrations. Kept as a constant so the cutoff is arguable, not buried.
STALE_BEFORE = 2024


def stale_events():
    return {k: v for k, v in EVENTS.items()
            if v[2] is not None and v[2] < STALE_BEFORE}


def event_entity(slug):
    """The unit that runs this event, as its own page states it."""
    hit = EVENTS.get(slug)
    return hit[0] if hit else ''


if __name__ == '__main__':
    stale = stale_events()
    print('events with a witnessed owner: %d of 44' % len(EVENTS))
    print('jointly owned by two entities: %d'
          % sum(1 for v in EVENTS.values() if ' AND ' in v[0]))
    print('last ran before %d — archive candidates: %d' % (STALE_BEFORE, len(stale)))
    for k, v in sorted(stale.items(), key=lambda x: x[1][2]):
        print('   %-24s %s   %s' % (k, v[2], v[0][:52]))
    print()
    print('still running (%d):' % (len(EVENTS) - len(stale)))
    for k, v in sorted(EVENTS.items(), key=lambda x: -(x[1][2] or 0)):
        if k not in stale:
            print('   %-24s %-6s %s' % (k, v[2] or '—', v[0][:52]))
