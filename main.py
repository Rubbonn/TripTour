'''
TripTour is a desktop application that transforms unstructured collections of photos into narrated virtual tours.
Copyright (C) 2026  Ruben Giuriato

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''

from app.images import Image
from app.models import ImageModel

img1 = Image('IMG_20260715_104924.jpg')
img_model = ImageModel.get(1)
if img_model is not None:
    img_model.delete()
img_model = ImageModel(id_tour=1, path=img1.path, filename=img1.filename, laplacian_variance=img1.laplacian_variance, embedding=img1.embedding)
img_model.save()

img_model = ImageModel.get(1)
print(img1.embedding, img_model.embedding, img1.embedding.equal(img_model.embedding))