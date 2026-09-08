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

from app.images import Image, remove_duplicate_images, read_dir

img1 = Image('IMG_20260715_104924.jpg')
img2 = Image('IMG_20260715_112410.jpg')
img3 = Image('IMG_20260715_122913.jpg')
img4 = Image('IMG_20260715_123023.jpg')
img5 = Image('IMG_20260715_122938.jpg')
images = read_dir('.')
remove_duplicate_images(images)
print([img.mime for img in images])