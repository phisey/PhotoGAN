from __future__ import print_function

import torch 
import torch.nn as nn 
import torch.optim as optim 
import matplotlib.pyplot as plt 
import torchvision.transforms as transforms
import torchvision.models as models 
import copy 
from torch.autograd import Variable 
from PIL import Image 

USE_CUDA = torch.cuda.is_available()
dtype = torch.cuda.FloatTensor if USE_CUDA else torch.FloatTensor

imsize = 512 if USE_CUDA else 128

loader = transforms.Compose([
    transforms.Resize([imsize,imsize]),
    transforms.ToTensor()
])

def image_loader(image_name):
    image = Image.open(image_name)
    image = Variable(loader(image))
    image = image.unsqueeze(0)
    return image 

style_img = image_loader("images/monet2.jpg").type(dtype)
content_img = image_loader("images/model.jpg").type(dtype)

assert style_img.size() == content_img.size(), "Content {:} and Style {:} Images must be of the same size".format(content_img.size(), style_img.size())

unloader = transforms.ToPILImage()

plt.ion()

def imshow(tensor, title=None):
    image = tensor.clone().cpu()
    image = image.view(3, imsize, imsize)
    image = unloader(image)
    plt.imshow(image)
    if title is not None:
        plt.title(title)
        plt.waitforbuttonpress()

# plt.figure()
# imshow(style_img.data, title="Style Image")
# plt.figure()
# imshow(content_img.data, title="Content Image")

# plt.show()

class ContentLoss(nn.Module):
    def __init__(self, target, weight):
        super(ContentLoss, self).__init__()
        self.target = target.detach() * weight
        self.weight = weight 
        self.criterion = nn.MSELoss()

    def forward(self, input):
        self.loss = self.criterion(input * self.weight, self.target)
        self.output = input 
        return self.output 

    def backward(self, retain_graph=True):
        self.loss.backward(retain_graph=retain_graph)
        return self.loss


class GramMatrix(nn.Module):
    def forward(self, input):
        a,b,c,d = input.size()
        features = input.view(a*b,c*d)
        G = torch.mm(features, features.t())
        return G.div(a * b * c * d)


class StyleLoss(nn.Module):
    def __init__(self, target, weight):
        super(StyleLoss, self).__init__()
        self.target = target.detach() * weight 
        self.weight = weight
        self.gram = GramMatrix()
        self.criterion = nn.MSELoss()

    def forward(self, input):
        self.output = input.clone()
        self.G = self.gram(input)
        self.G.mul_(self.weight)
        self.loss = self.criterion(self.G, self.target)
        return self.output 

    def backward(self, retain_graph=True):
        self.loss.backward(retain_graph=True)
        return self.loss 


cnn = models.vgg19(pretrained=True).features
if USE_CUDA:
    cnn = cnn.cuda()

content_layers_default = ['conv_4']
style_layers_default = ['conv_1', 'conv_2', 'conv_3','conv_4','conv_5']

def get_style_model_and_losses(cnn, style_img, content_img, style_weight=1000, content_weight=1, 
                                content_layers=content_layers_default, style_layers=style_layers_default):
    cnn = copy.deepcopy(cnn)
    content_losses = []
    style_losses = []
    model = nn.Sequential()
    gram = GramMatrix()

    if USE_CUDA:
        model = model.cuda()
        gram = gram.cuda()
    
    i = 1 
    for layer in list(cnn):
        if isinstance(layer, nn.Conv2d):
            name = "conv_" + str(i)
            model.add_module(name, layer)

            if name in content_layers:
                target = model(content_img).clone()
                content_loss = ContentLoss(target, content_weight)
                model.add_module("content_loss_" + str(i), content_loss)
                content_losses.append(content_loss)

            if name in style_layers:
                target_feature = model(style_img).clone()
                target_feature_gram = gram(target_feature)
                style_loss = StyleLoss(target_feature_gram, style_weight)
                model.add_module("style_loss_" + str(i), style_loss)
                style_losses.append(style_loss)

        if isinstance(layer, nn.ReLU):
            name = "relu_" + str(i)
            model.add_module(name, layer)

            if name in content_layers:
                target = model(content_img).clone()
                content_loss = ContentLoss(target, content_weight)
                model.add_module("content_loss_" + str(i), content_loss)
                content_losses.append(content_loss)
                
            if name in style_layers:
                target_feature = model(style_img).clone()
                target_feature_gram = gram(target_feature)
                style_loss = StyleLoss(target_feature_gram, style_weight)
                model.add_module("style_loss_" + str(i), style_loss)
                style_losses.append(style_loss)
            
            i += 1

        if isinstance(layer, nn.MaxPool2d):
            name = "pool_" + str(i)
            model.add_module(name, layer)

    return model, style_losses, content_losses 

input_img = content_img.clone()
# input_img = Variable(torch.randn(content_img.data.size())).type(dtype) 
# plt.figure()
# imshow(input_img.data, title="Input Image") 

def get_input_param_optimizer(input_img):
    input_param = nn.Parameter(input_img.data)
    optimizer = optim.LBFGS([input_param])
    return input_param, optimizer

def run_style_transfer(cnn, content_img, style_img, input_img, num_steps=1000, style_weight=1000, content_weight=1):
    """Run the style transfer"""
    print("Building the style transfer model ...")
    model, style_losses, content_losses = get_style_model_and_losses(cnn, style_img, content_img, style_weight, content_weight)
    input_param, optimizer = get_input_param_optimizer(input_img)
    print("Optimizing ...")
    run = [0]
    while run[0] <= num_steps:
        def closure():
            input_param.data.clamp_(0,1)
            optimizer.zero_grad()
            model(input_param)
            style_score = 0
            content_score = 0

            for sl in style_losses:
                style_score += sl.backward()
            for cl in content_losses:
                content_score += cl.backward()

            run[0] += 1
            if run[0] % 50 == 0:
                print("run {:}:".format(run))
                print("Style loss: {:4f} Content Loss: {:4f}".format(style_score.data[0], content_score.data[0]))
                print()
            return style_score + content_score
        optimizer.step(closure)
    input_param.data.clamp_(0,1)
    return input_param.data

output = run_style_transfer(cnn, content_img, style_img, input_img)
plt.figure()
imshow(output, title="Output Image")
plt.ioff()
plt.show()