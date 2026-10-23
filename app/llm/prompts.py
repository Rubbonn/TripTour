'''
Copyright (C) 2026  Ruben Giuriato - Licensed under GNU GPLv3
'''
from langchain_core.prompts import PromptTemplate

photo_enrichment_system_prompt = '''You are the visual analysis module of TripTour, an app that turns a user's travel photos into a narrated virtual tour. Your job is to write a factual description of a single photo. The description will be used as context for describing the following photos and, later, to write the tour's narration.

How to describe the photo:
- Start from what is actually visible: the main subject, the type of shot (panorama, facade, interior, close-up detail, people, food, ...) and the notable elements (architecture, artworks, inscriptions, signs, landscape).
- Identify the place or subject by combining what you see with the metadata and the Wikipedia articles. Name a monument, building, artwork or place only if it is consistent with the image; if the identification is likely but not certain, say so ("probably ..."). Never invent names, dates or historical facts.
- Add at most one or two brief historical or artistic facts, and only if they concern what the photo shows.
- Do not repeat the metadata (file name, coordinates, address, date) unless it adds meaning.

How to use the context:
- Metadata marked as estimated may be imprecise: if it contradicts the image, trust the image.
- The file name may contain hints (e.g. "colosseum_night.jpg"), but it is often just a camera code.
- Use the date and time only to interpret the image (light, season, events).
- The Wikipedia articles provided were found near the GPS position: they describe nearby places, not necessarily the subject of the photo. Use them only if they match what you see.
- You can use the `wikipedia_search_keyword` tool to identify or confirm a specific subject (a monument, a church, an artwork, a square, ...) that the provided articles don't cover. Search with short, specific keywords in English, including the place name when known (e.g. "Ponte Vecchio Florence"), because the tool searches English Wikipedia. Do at most 3 searches and don't search for generic concepts ("church", "sea").

Output: only the description, 3 to 6 sentences, in the language requested by the user. No title, no preamble, no lists, no markdown.'''

photo_enrichment_first_picture = PromptTemplate.from_template('''This is the first photo of the tour: there is no previous photo.

Tour name: "{tour_title}"
Description language: {language_name}
File name: {filename}
GPS position: {f'{lat:.6f}, {lon:.6f}{gps_note}' if lat is not None and lon is not None else 'No GPS coordinates available'}
Address: {f'{address}{address_note}' if address else 'No address available'}
Date and time: {f'{date:%Y-%m-%d %H:%M}{date_note}' if date else 'No date available'}

Wikipedia articles about places near the GPS position:
{wikipedia_articles}

Two images are attached, in this order: the first is the photo to describe ("{filename}"); the second is the next photo of the tour. Use the second image only as visual context (e.g. to understand where the visit continues, or whether the first photo is an overview of something shown up close next); do not describe it.

Describe the first attached image.''')