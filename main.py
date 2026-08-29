from app.image import Image
from app.models import ImageModel

img1 = Image('IMG_20260715_104924.jpg')
img_model = ImageModel.get(1).delete()
img_model = ImageModel(id_tour=1, path=img1.path, filename=img1.filename, laplacian_variance=img1.laplacian_variance, embedding=img1.embedding)
img_model.save()

img_model = ImageModel.get(1)
print(img1.embedding, img_model.embedding, img1.embedding.equal(img_model.embedding))