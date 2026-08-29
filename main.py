from app.models import Tour

t = Tour(title="Sample Tour", language="en")
t.save()

print(Tour.all())