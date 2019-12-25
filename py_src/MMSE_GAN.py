import numpy as np
from os import listdir, makedirs, getcwd, remove
from os.path import isfile, join, abspath, exists, isdir, expanduser

import torch
from torch.autograd import Variable
import torch.nn as nn
import torch.autograd as autograd
from torch.utils.data import Dataset, DataLoader
import torch.utils.data as data
import torch.nn.functional as F
import torch.optim as optim

import torchvision
from torchvision import transforms, datasets, models
from torch import Tensor

import visdom
import math
import matplotlib.pyplot as plt 
import scipy
from scipy import io as sio
from scipy.io import savemat
from scipy.io import loadmat

from dataloaders import parallel_dataloader
from networks import dnn_generator, dnn_discriminator
from utils import *

# Connect with Visdom for the loss visualization
viz = visdom.Visdom()

# Path where you want to store your results        
mainfolder = "../dataset/features/US_102/batches/mcc/"
checkpoint = "../results/checkpoints/mcc/"

# Training Data path
traindata = parallel_dataloader(folder_path=mainfolder)
train_dataloader = DataLoader(dataset=traindata, batch_size=1, shuffle=True, num_workers=2)  # For windows keep num_workers = 0


# Path for validation data
valdata = parallel_dataloader(folder_path=mainfolder)
val_dataloader = DataLoader(dataset=valdata, batch_size=1, shuffle=True, num_workers=2)  # For windows keep num_workers = 0


# Loss Functions
adversarial_loss = nn.BCELoss()
mmse_loss = nn.MSELoss()

ip_g = 40 # MCEP feature dimentions
op_g = 40 # MCEP feature dimentions
ip_d = 40 # MCEP feature dimentions
op_d = 1


# Check for Cuda availability
if torch.cuda.is_available():
    decive = 'cuda:0'
else:
    device = 'cpu'

# Initialization 
Gnet = dnn_generator(ip_g, op_g, 512, 512, 512).to(device)
Dnet = dnn_discriminator(ip_d, op_d, 512, 512, 512).to(device)


# Initialize the optimizers
optimizer_G = torch.optim.Adam(Gnet.parameters(), lr=0.0001)
optimizer_D = torch.optim.Adam(Dnet.parameters(), lr=0.0001)



# Training Function
def training(data_loader, n_epochs):
    Gnet.train()
    Dnet.train()
    
    for en, (a, b) in enumerate(data_loader):
        a = Variable(a.squeeze(0).type(torch.FloatTensor)).to(device)
        b = Variable(b.squeeze(0).type(torch.FloatTensor)).to(device)

        valid = Variable(Tensor(a.shape[0], 1).fill_(1.0), requires_grad=False).to(device)
        fake = Variable(Tensor(a.shape[0], 1).fill_(0.0), requires_grad=False).to(device)
        
        # Update G network
        optimizer_G.zero_grad()
        Gout = Gnet(a)
        
        G_loss = adversarial_loss(Dnet(Gout), valid) + mmse_loss(Gout, b)
        
        G_loss.backward()
        optimizer_G.step()


        # Update D network
        optimizer_D.zero_grad()

        # Measure discriminator's ability to classify real from generated samples
        real_loss = adversarial_loss(Dnet(b), valid)
        fake_loss = adversarial_loss(Dnet(Gout.detach()), fake)
        D_loss = (real_loss + fake_loss) / 2
        
        D_loss.backward()
        optimizer_D.step()
        
        
        print ("[Epoch: %d] [Iter: %d/%d] [D loss: %f] [G loss: %f]" % (n_epochs, en, len(data_loader), D_loss, G_loss.cpu().data.numpy()))
    

# Validation function
def validating(data_loader):
    Gnet.eval()
    Dnet.eval()
    Grunning_loss = 0
    Drunning_loss = 0
    
    for en, (a, b) in enumerate(data_loader):
        a = Variable(a.squeeze(0).type(torch.FloatTensor)).to(device)
        b = Variable(b.squeeze(0).type(torch.FloatTensor)).to(device)

        valid = Variable(Tensor(a.shape[0], 1).fill_(1.0), requires_grad=False).to(device)
        fake = Variable(Tensor(a.shape[0], 1).fill_(0.0), requires_grad=False).to(device)
        
        Gout = Gnet(a)
        G_loss = adversarial_loss(Dnet(Gout), valid) + mmse_loss(Gout, b)

        Grunning_loss += G_loss.item()


        real_loss = adversarial_loss(Dnet(b), valid)
        fake_loss = adversarial_loss(Dnet(Gout.detach()), fake)
        D_loss = (real_loss + fake_loss) / 2
        
        Drunning_loss += D_loss.item()
        
    return Drunning_loss/(en+1),Grunning_loss/(en+1)



def do_training():
    epoch = 100
    dl_arr = []
    gl_arr = []
    for ep in range(epoch):

        training(train_dataloader, ep+1)
        if (ep+1)%5==0:
            torch.save(Gnet, join(checkpoint,"gen_Ep_{}.pth".format(ep+1)))
            torch.save(Dnet, join(checkpoint,"dis_Ep_{}.pth".format(ep+1)))
        dl,gl = validating(val_dataloader)
        print("D_loss: " + str(dl) + " G_loss: " + str(gl))
        dl_arr.append(dl)
        gl_arr.append(gl)
        if ep == 0:
            gplot = viz.line(Y=np.array([gl]), X=np.array([ep]), opts=dict(title='Generator'))
            dplot = viz.line(Y=np.array([dl]), X=np.array([ep]), opts=dict(title='Discriminator'))
        else:
            viz.line(Y=np.array([gl]), X=np.array([ep]), win=gplot, update='append')
            viz.line(Y=np.array([dl]), X=np.array([ep]), win=dplot, update='append')

            
    savemat(checkpoint+"/"+str('discriminator_loss.mat'),  mdict={'foo': dl_arr})
    savemat(checkpoint+"/"+str('generator_loss.mat'),  mdict={'foo': gl_arr})

    plt.figure(1)
    plt.plot(dl_arr)
    plt.savefig(checkpoint+'/discriminator_loss.png')
    plt.figure(2)
    plt.plot(gl_arr)
    plt.savefig(checkpoint+'/generator_loss.png')



'''
Testing on training dataset as of now. Later it will be modified according to the different shell scripts.
'''


def do_testing():
    print("Testing")
    save_folder = "../results/mask/mcc"
    test_folder_path="../dataset/features/batches/mcc"  # Change the folder path to testing directory. (Later)
    dirs = listdir(test_folder_path)
    Gnet = torch.load(join(mainfolder,"gen_ws_Ep_100.pth"))

    for i in dirs:
        
        # Load the .mcc file
        d = read_mcc(join(test_folder_path, i))

        a = torch.from_numpy(d['Feat'])
        a = Variable(a.squeeze(0).type('torch.FloatTensor')).cuda()
        
        Gout = Gnet(a)

        savemat(join(save_folder,'{}.mat'.format(i[:-4])),  mdict={'foo': Gout.cpu().data.numpy()})


'''
Check MCD value on validation data for now! :)
'''


def give_MCD():
    Gnet = torch.load(join(checkpoint,"gen_Ep_100.pth"))
    mcd = []

    for en, (a, b) in enumerate(val_dataloader):
        a = Variable(a.squeeze(0).type(torch.FloatTensor)).cuda()
        b = b.cpu().data.numpy()[0]

        Gout = Gnet(a).cpu().data.numpy()

        ans = 0
        for k in range(Gout.shape[0]):
            ans = logSpecDbDist(Gout[k][1:],b[k][1:])
            mcd.append(ans)

    mcd = np.array(mcd)
    print(np.mean(mcd))


if __name__ == '__main__':
    do_training()
    do_testing()
    give_MCD()