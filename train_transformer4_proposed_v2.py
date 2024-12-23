import torch
import torch.utils.data
import torch.nn as nn
import torch.optim as optim
import torchvision.transforms
from torch.utils.data import DataLoader
from torch.autograd import Variable
from torchvision import transforms
from torchvision.transforms import ToTensor, Normalize, Resize, CenterCrop
import os
from os.path import join, basename, splitext
from models.build4 import build_model, ImagePool
# from models.Generator_former import Generator_former
from utils.loss import *
from models.Discriminator_ml import MsImageDis
# from utils.utils import gaussian_weight
from tensorboardX import SummaryWriter
from dataset import dataset_norm
import argparse
from datetime import datetime
from torch.utils.data import Dataset, DataLoader, TensorDataset
import random
from loss import *
import torchvision.models as models

from utils.utils import *


# this version is with normlized input with mean and std, all layers are normalized,
# change the order of the 'make_layer' with norm-activate-conv,and use the multi-scal D
# use two kind feature, horizon and vertical

os.environ["CUDA_VISIBLE_DEVICES"] = "0"

def seed_everything(seed):
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = True

# Training
def train(gen, dis, opt_gen, opt_dis, epoch, train_loader, writer):  #24.09.19 recognizer
    gen.train()
    dis.train()

    # mse = nn.MSELoss().cuda(0)
    mae = nn.L1Loss().cuda(0)  # 평균 절대 오차(MAE)를 사용하여 픽셀 간의 차이 계산
    mrf = IDMRFLoss(device=0)  # 텍스처 일관성 평가
    # ssim_loss = SSIM_loss().cuda(0)  # 구조적 유사성
    # fs_loss = FS_Loss().cuda(0)

    # content_loss = ContentLoss().cuda(0)
    style_loss = StyleLoss().cuda(0)

    acc_pixel_rec_loss = 0
    acc_feat_rec_loss = 0
    acc_mrf_loss = 0
    acc_feat_cons_loss = 0
    acc_gen_adv_loss = 0
    acc_dis_adv_loss = 0
    # acc_ssim_loss = 0
    # acc_fs_loss = 0

    acc_style_loss = 0
    # acc_content_loss = 0
    # acc_perceptual_loss = 0

    total_gen_loss = 0

    for batch_idx, (gt, mask_img) in enumerate(train_loader):  # 24.09.20 수정
        batchSize = mask_img.shape[0]
        imgSize = mask_img.shape[2]

        # gt, mask_img, iner_img = Variable(gt).cuda(0), Variable(mask_img.type(torch.FloatTensor)).cuda(0), Variable(iner_img).cuda(0)
        gt, mask_img = Variable(gt).cuda(0), Variable(mask_img.type(torch.FloatTensor)).cuda(0)

        iner_img = gt[:, :, :, 32:32 + 128]  # 가로로 32~160 pixel
        # I_groundtruth = torch.cat((I_l, I_r), 3)  # shape: B,C,H,W

        ## feature size 맞춰주기 f_de 와 f_en
        ## Generate Image
        I_pred, f_de = gen(mask_img)  # 생성된 image, 중간 feature map
        # I_pred = gen(mask_img)
        f_en = gen(iner_img, only_encode=True)  #iner_img(GT)를 encoding하여 feature map을 얻음

        # i_mask = torch.ones_like(gt)
        # i_mask[:, :, 32:32 + 128, 32:32 + 128] = 0
        # mask_pred = I_pred * i_mask
        mask_pred = I_pred[:, :, :, 32:32 + 128]  # 생성된 image의 일부분 선택

        ## Compute losses
        ## Update Discriminator
        opt_dis.zero_grad()
        dis_adv_loss = dis.calc_dis_loss(I_pred.detach(), gt)  # 생성된 image와 gt와의 구별 능력 학습
        dis_loss = dis_adv_loss
        dis_loss.backward()
        opt_dis.step()  # 가중치 update

        # Pixel Reconstruction Loss
        # pixel_rec_loss = mse(I_pred, gt) * 10
        # pixel_rec_loss = mse(mask_pred, iner_img) * 10
        pixel_rec_loss = mae(I_pred, gt) * 20  # pixel 재구성 손실

        # Texture Consistency Loss (IDMRF Loss)
        # mrf_loss = mrf(((I_pred * img_mask).cuda(0) + 1) / 2.0, ((gt * img_mask).cuda(0) + 1) / 2.0) * 0.01 / batchSize
        mrf_loss = mrf((mask_pred.cuda(0) + 1) / 2.0, (iner_img.cuda(0) + 1) / 2.0) * 0.5 / batchSize  # 텍스처 일관성 손실
        # mrf_loss = mrf((I_pred_split[1].cuda(1)+1)/2.0, (I_m.cuda(1)+1)/2.0) * 0.01

        # Feature Reconstruction Loss
        # feat_rec_loss = mse(f_all, f_all_gt.detach()).mean() * batchSize
        # feat_rec_loss = mse(f_all, f_all_gt.detach()) * 5

        ### dimension 맞춰주기 진행
        feat_rec_loss = mae(f_de, f_en.detach())  # 생성된 imgae의 feature map과 gt의 feature map 간의 L1 손실

        # ### SSIM loss
        # left_loss = ssim_loss(I_pred[:, :, :, 0:32], I_pred[:, :, :, 32:64])
        # right_loss = ssim_loss(I_pred[:, :, :, 160:192], I_pred[:, :, :, 128:160])
        # total_ssim_loss = left_loss+right_loss

        # # 24.10.29 Feature Similarity Loss (MSOI loss)
        # left_loss = fs_loss(I_pred[:, :, :, 0:32], I_pred[:, :, :, 32:64])
        # right_loss = fs_loss(I_pred[:, :, :, 160:192], I_pred[:, :, :, 128:160])
        # total_fs_loss = left_loss + right_loss

        # # 24.11.04 Perceptual Loss
        # content_left_loss = content_loss(I_pred[:, :, :, 0:32], I_pred[:, :, :, 32:64])
        # content_right_loss = content_loss(I_pred[:, :, :, 160:192], I_pred[:, :, :, 128:160])
        # total_content_loss = content_left_loss + content_right_loss

        style_left_loss = style_loss(I_pred[:, :, :, 0:32], I_pred[:, :, :, 32:64])
        style_right_loss = style_loss(I_pred[:, :, :, 160:192], I_pred[:, :, :, 128:160])
        total_style_loss = style_left_loss + style_right_loss

        # total_perceptual_loss = total_content_loss + total_style_loss

        # ## Update Generator
        gen_adv_loss = dis.calc_gen_loss(I_pred, gt)  # generator에 대한 적대적 손실
        # gen_loss = pixel_rec_loss + gen_adv_loss + mrf_loss.cuda(0) + feat_rec_loss

        # gen_loss = pixel_rec_loss + gen_adv_loss + feat_rec_loss + mrf_loss.cuda(0) + total_perceptual_loss  # 24.11.04 Perceptual Loss
        gen_loss = pixel_rec_loss + gen_adv_loss + feat_rec_loss + mrf_loss.cuda(0) + total_style_loss  # 24.11.04 Perceptual Loss

        opt_gen.zero_grad()
        gen_loss.backward()
        opt_gen.step()

        acc_pixel_rec_loss += pixel_rec_loss.data
        acc_gen_adv_loss += gen_adv_loss.data
        acc_mrf_loss += mrf_loss.data
        acc_feat_rec_loss += feat_rec_loss.data
        # acc_feat_cons_loss += feat_cons_loss.data
        acc_dis_adv_loss += dis_adv_loss.data
        # acc_ssim_loss += total_ssim_loss

        acc_style_loss += total_style_loss.data
        # acc_content_loss += total_content_loss.data
        # acc_perceptual_loss += total_perceptual_loss.data  # 24.11.04 perceptual_loss

        total_gen_loss += gen_loss.data

        if batch_idx % 10 == 0:
            print("train iter %d" % batch_idx)
            print('generate_loss:', gen_loss.item())
            print('dis_loss:', dis_loss.item())

    ## Tensor board
    writer.add_scalars('train/generator_loss',
                       {'Pixel Reconstruction Loss': acc_pixel_rec_loss / len(train_loader.dataset)}, epoch)
    writer.add_scalars('train/generator_loss', {'Texture Consistency Loss': acc_mrf_loss / len(train_loader.dataset)},
                       epoch)
    writer.add_scalars('train/generator_loss',
                       {'Feature Reconstruction Loss': acc_feat_rec_loss / len(train_loader.dataset)}, epoch)
    # writer.add_scalars('train/generator_loss', {'Feature Consistency Loss': acc_feat_cons_loss / len(train_loader.dataset)}, epoch)
    writer.add_scalars('train/generator_loss', {'Adversarial Loss': acc_gen_adv_loss / len(train_loader.dataset)},
                       epoch)
    # writer.add_scalars('train/SSIM_loss', {'total gen Loss': acc_ssim_loss / len(train_loader.dataset)},
    #                    epoch)
    # writer.add_scalars('train/fs_loss', {'total gen Loss': acc_fs_loss / len(train_loader.dataset)},
    #                    epoch)   # 24.10.29 fs_loss

    # writer.add_scalars('train/perceptual_loss', {'Style Loss': acc_style_loss / len(train_loader.dataset)},
    #                    epoch)  # 24.11.04 perceptual_loss
    # writer.add_scalars('train/perceptual_loss', {'Content Loss': acc_content_loss / len(train_loader.dataset)},
    #                    epoch)  # 24.11.04 perceptual_loss
    # writer.add_scalars('train/generator_loss', {'Perceptual Loss': acc_perceptual_loss / len(train_loader.dataset)},
    #                    epoch)  # 24.11.04 perceptual_loss

    writer.add_scalars('train/style_loss', {'Style Loss': acc_style_loss / len(train_loader.dataset)},
                       epoch)  # 24.11.04 perceptual_loss
    writer.add_scalars('train/generator_loss', {'Style Loss': acc_style_loss / len(train_loader.dataset)},
                       epoch)  # 24.11.04 perceptual_loss


    writer.add_scalars('train/total_gen_loss', {'total gen Loss': total_gen_loss / len(train_loader.dataset)},
                       epoch)
    writer.add_scalars('train/discriminator_loss', {'Adversarial Loss': acc_dis_adv_loss / len(train_loader.dataset)},
                       epoch)

# Training
def valid(gen, dis, opt_gen, opt_dis, epoch, valid_loader, writer):
    gen.eval()
    dis.eval()

    # mse = nn.MSELoss().cuda(0)
    mae = nn.L1Loss().cuda(0)
    mrf = IDMRFLoss(device=0)
    # ssim_loss = SSIM_loss().cuda(0)
    # perceptual_loss = Perceptual_loss().cuda(0)
    # content_loss = ContentLoss().cuda(0)
    style_loss = StyleLoss().cuda(0)

    acc_pixel_rec_loss = 0
    acc_feat_rec_loss = 0
    acc_mrf_loss = 0
    acc_feat_cons_loss = 0
    acc_gen_adv_loss = 0
    acc_dis_adv_loss = 0
    # acc_ssim_loss = 0
    # acc_fs_loss = 0

    acc_style_loss = 0
    # acc_content_loss = 0
    # acc_perceptual_loss = 0

    total_gen_loss = 0

    for batch_idx, (gt, mask_img) in enumerate(valid_loader):  # 24.09.19 labels 추가 / 관련 matching 수정 필요
        batchSize = mask_img.shape[0]
        imgSize = mask_img.shape[2]

        # gt, mask_img, iner_img = Variable(gt).cuda(0), Variable(mask_img.type(torch.FloatTensor)).cuda(0), Variable(iner_img).cuda(0)
        gt, mask_img = Variable(gt).cuda(0), Variable(mask_img.type(torch.FloatTensor)).cuda(0)

        iner_img = gt[:, :, :, 32:32 + 128]
        # I_groundtruth = torch.cat((I_l, I_r), 3)  # shape: B,C,H,W

        ## feature size match f_de and f_en
        ## Generate Image
        with torch.no_grad():
            I_pred, f_de = gen(mask_img)
        # I_pred = gen(mask_img)
        with torch.no_grad():
            f_en = gen(iner_img, only_encode=True)

        # i_mask = torch.ones_like(gt)
        # i_mask[:, :, 32:32 + 128, 32:32 + 128] = 0
        # mask_pred = I_pred * i_mask
        mask_pred = I_pred[:, :, :, 32:32 + 128]

        ## Compute losses
        ## Update Discriminator
        opt_dis.zero_grad()
        dis_adv_loss = dis.calc_dis_loss(I_pred.detach(), gt)
        dis_loss = dis_adv_loss

        # Pixel Reconstruction Loss
        # pixel_rec_loss = mse(I_pred, gt) * 10
        # pixel_rec_loss = mse(mask_pred, iner_img) * 10
        pixel_rec_loss = mae(I_pred, gt) * 20

        # Texture Consistency Loss (IDMRF Loss)
        # mrf_loss = mrf(((I_pred * img_mask).cuda(0) + 1) / 2.0, ((gt * img_mask).cuda(0) + 1) / 2.0) * 0.01 / batchSize
        mrf_loss = mrf((mask_pred.cuda(0) + 1) / 2.0, (iner_img.cuda(0) + 1) / 2.0) * 0.5 / batchSize
        # mrf_loss = mrf((I_pred_split[1].cuda(1)+1)/2.0, (I_m.cuda(1)+1)/2.0) * 0.01

        # Feature Reconstruction Loss
        # feat_rec_loss = mse(f_all, f_all_gt.detach()).mean() * batchSize
        # feat_rec_loss = mse(f_all, f_all_gt.detach()) * 5

        ### dimension 맞춰주기 진행
        feat_rec_loss = mae(f_de, f_en.detach())

        # ## Update Generator

        # ### SSIM loss
        # left_loss = ssim_loss(I_pred[:, :, :, 0:32], I_pred[:, :, :, 32:64])
        # right_loss = ssim_loss(I_pred[:, :, :, 160:192], I_pred[:, :, :, 128:160])
        # total_ssim_loss = left_loss + right_loss

        # # 24.10.29 Feature Similarity Loss (MSOI loss)
        # left_loss = fs_loss(I_pred[:, :, :, 0:32], I_pred[:, :, :, 32:64])
        # right_loss = fs_loss(I_pred[:, :, :, 160:192], I_pred[:, :, :, 128:160])
        # total_fs_loss = left_loss + right_loss

        # # 24.11.04 Perceptual Loss
        # content_left_loss = content_loss(I_pred[:, :, :, 0:32], I_pred[:, :, :, 32:64])
        # content_right_loss = content_loss(I_pred[:, :, :, 160:192], I_pred[:, :, :, 128:160])
        # total_content_loss = content_left_loss + content_right_loss

        style_left_loss = style_loss(I_pred[:, :, :, 0:32], I_pred[:, :, :, 32:64])
        style_right_loss = style_loss(I_pred[:, :, :, 160:192], I_pred[:, :, :, 128:160])
        total_style_loss = style_left_loss + style_right_loss

        # total_perceptual_loss = total_content_loss + total_style_loss

        gen_adv_loss = dis.calc_gen_loss(I_pred, gt)
        # gen_loss = pixel_rec_loss + gen_adv_loss + mrf_loss.cuda(0) + feat_rec_loss

        # gen_loss = pixel_rec_loss + gen_adv_loss + feat_rec_loss + mrf_loss.cuda(0) + total_perceptual_loss  # 24.11.04 Perceptual Loss
        gen_loss = pixel_rec_loss + gen_adv_loss + feat_rec_loss + mrf_loss.cuda(0) + total_style_loss  # 24.11.04 Perceptual Loss

        opt_gen.zero_grad()

        acc_pixel_rec_loss += pixel_rec_loss.data
        acc_gen_adv_loss += gen_adv_loss.data
        acc_mrf_loss += mrf_loss.data
        acc_feat_rec_loss += feat_rec_loss.data
        # acc_feat_cons_loss += feat_cons_loss.data
        acc_dis_adv_loss += dis_adv_loss.data
        # acc_ssim_loss += total_ssim_loss.data

        acc_style_loss += total_style_loss.data
        # acc_content_loss += total_content_loss.data
        # acc_perceptual_loss += total_perceptual_loss.data  # 24.11.04 perceptual_loss

        total_gen_loss += gen_loss.data


    ## Tensor board
    writer.add_scalars('valid/generator_loss',
                       {'Pixel Reconstruction Loss': acc_pixel_rec_loss / len(valid_loader.dataset)}, epoch)
    writer.add_scalars('valid/generator_loss', {'Texture Consistency Loss': acc_mrf_loss / len(valid_loader.dataset)},
                       epoch)
    writer.add_scalars('valid/generator_loss',
                       {'Feature Reconstruction Loss': acc_feat_rec_loss / len(valid_loader.dataset)}, epoch)
    # writer.add_scalars('train/generator_loss', {'Feature Consistency Loss': acc_feat_cons_loss / len(train_loader.dataset)}, epoch)
    writer.add_scalars('valid/generator_loss', {'Adversarial Loss': acc_gen_adv_loss / len(valid_loader.dataset)},
                       epoch)

    # writer.add_scalars('valid/SSIM_loss', {'total gen Loss': acc_ssim_loss / len(valid_loader.dataset)},
    #                    epoch)
    # writer.add_scalars('valid/fs_loss', {'total gen Loss': acc_fs_loss / len(valid_loader.dataset)},
    #                    epoch)  # 24.10.29 fs_loss

    # writer.add_scalars('valid/perceptual_loss', {'Style Loss': acc_style_loss / len(valid_loader.dataset)},
    #                    epoch)  # 24.11.04 perceptual_loss
    # writer.add_scalars('valid/perceptual_loss', {'Content Loss': acc_content_loss / len(valid_loader.dataset)},
    #                    epoch)  # 24.11.04 perceptual_loss
    # writer.add_scalars('valid/generator_loss', {'Perceptual Loss': acc_perceptual_loss / len(valid_loader.dataset)},
    #                    epoch)  # 24.11.04 perceptual_loss
    
    writer.add_scalars('valid/style_loss', {'Style Loss': acc_style_loss / len(valid_loader.dataset)},
                       epoch)  # 24.11.04 perceptual_loss
    writer.add_scalars('valid/generator_loss', {'Style Loss': acc_style_loss / len(valid_loader.dataset)},
                       epoch)  # 24.11.04 perceptual_loss
    
    
    writer.add_scalars('valid/total_gen_loss', {'total gen Loss': total_gen_loss / len(valid_loader.dataset)},
                       epoch)
    writer.add_scalars('valid/discriminator_loss', {'Adversarial Loss': acc_dis_adv_loss / len(valid_loader.dataset)},
                       epoch)

if __name__ == '__main__':

    SAVE_WEIGHT_DIR = '/content/drive/MyDrive/perceptual/output/SDdb-1/checkpoints'  
    SAVE_LOG_DIR = '/content/drive/MyDrive/perceptual/output/SDdb-1/logs_all'  
    LOAD_WEIGHT_DIR = '/content/drive/MyDrive/perceptual/output/SDdb-1/checkpoints'  # 24.11.14 SDdb-1
    TRAIN_DATA_DIR = ''

    seed_everything(2024)  # Seed 고정


    def get_args():

        parser = argparse.ArgumentParser()

        parser.add_argument('--train_batch_size', type=int, help='batch size of training data', default=2)
        parser.add_argument('--test_batch_size', type=int, help='batch size of testing data', default=16)
        parser.add_argument('--epochs', type=int, help='number of epoches', default=700)
        parser.add_argument('--lr', type=float, help='learning rate', default=0.0004)
        parser.add_argument('--alpha', type=float, help='learning rate decay for discriminator', default=0.1)
        parser.add_argument('--load_pretrain', type=bool, help='load pretrain weight', default=False)  # pretrain !!!
        parser.add_argument('--test_flag', type=bool, help='testing while training', default=False)
        parser.add_argument('--adjoint', type=bool, help='if use adjoint in odenet', default=True)

        # parser.add_argument('--skip_connection', type=int,help='layers with skip connection', nargs='+', default=[0,1,2,3,4])
        # parser.add_argument('--attention', type=int,help='layers with attention mechanism applied on skip connection', nargs='+', default=[1])

        parser.add_argument('--load_weight_dir', type=str, help='directory of pretrain model weights',
                            default=LOAD_WEIGHT_DIR)
        parser.add_argument('--save_weight_dir', type=str, help='directory of saving model weights',
                            default=SAVE_WEIGHT_DIR)
        parser.add_argument('--log_dir', type=str, help='directory of saving logs', default=SAVE_LOG_DIR)
        parser.add_argument('--train_data_dir', type=str, help='directory of training data', default=TRAIN_DATA_DIR)
        # parser.add_argument('--test_data_dir', type=str, help='directory of testing data', default=TEST_DATA_DIR)
        # parser.add_argument('--gpu', type=str, help='gpu device', default='0')

        opts = parser.parse_args()
        return opts

    args = get_args()
    config = {}
    config['pre_step'] = 1
    config['TYPE'] = 'swin_cross_attn_ResB_v2'
    config['IMG_SIZE'] = 224
    config['SWIN.PATCH_SIZE'] = 4
    config['SWIN.IN_CHANS'] = 3
    config['SWIN.EMBED_DIM'] = 96
    config['SWIN.DEPTHS'] = [2, 2, 6, 2]
    config['SWIN.NUM_HEADS'] = [3, 6, 12, 24]
    config['SWIN.WINDOW_SIZE'] = 7
    config['SWIN.MLP_RATIO'] = 4.
    config['SWIN.QKV_BIAS'] = True
    config['SWIN.QK_SCALE'] = None
    config['DROP_RATE'] = 0.0
    config['DROP_PATH_RATE'] = 0.2
    config['SWIN.PATCH_NORM'] = True
    config['TRAIN.USE_CHECKPOINT'] = False

    ## 2023 11 08 class-wise하게 8:2로 나눠줌
    base_dir = '/content'
    HKdb_dir = 'HK-db/HKdb_1'  # 24.11.09 HKDB-1
    SDdb_dir = 'SD-db/SDdb_1'  # 24.11.14 SDdb-1

    # 각 서브 폴더의 경로를 설정
    original_dir = join(base_dir, 'original_images_split', SDdb_dir)  
    mask_dir = join(base_dir, 'mask_images_split_con', SDdb_dir)  
    clahe_dir = join(base_dir, 'clahe_images_split', SDdb_dir)  # 24.11.12 SDDB-1

    # 각 디렉토리가 존재하는지 확인
    assert os.path.isdir(original_dir), f"Original directory does not exist: {original_dir}"
    assert os.path.isdir(mask_dir), f"Mask directory does not exist: {mask_dir}"
    assert os.path.isdir(clahe_dir), f"CLAHE directory does not exist: {clahe_dir}"

    # 이미지 파일 리스트를 가져옴
    original_list = glob(original_dir, '*', True)
    mask_list = glob(mask_dir, '*', True)
    clahe_list = glob(clahe_dir, '*', True)

    # 각 리스트의 길이가 동일한지 확인
    assert len(original_list) == len(mask_list) == len(clahe_list)

    # 리스트 길이 출력
    print('Original list:', len(original_list))
    print('Mask list:', len(mask_list))
    print('CLAHE list:', len(clahe_list))

    # 데이터셋을 학습용과 검증용으로 분할
    train_ls_original, train_ls_mask, train_ls_clahe = [], [], []
    valid_ls_original, valid_ls_mask, valid_ls_clahe = [], [], []

    train_ls_original_list = original_list[:int(len(original_list) * 0.8)]
    train_ls_mask_list = mask_list[:int(len(mask_list) * 0.8)]
    train_ls_clahe_list = clahe_list[:int(len(clahe_list) * 0.8)]

    valid_ls_original_list = original_list[int(len(original_list) * 0.8):]
    valid_ls_mask_list = mask_list[int(len(mask_list) * 0.8):]
    valid_ls_clahe_list = clahe_list[int(len(clahe_list) * 0.8):]

    for path in train_ls_original_list:
        train_ls_original += glob(path, '*', True)

    for path in train_ls_mask_list:
        train_ls_mask += glob(path, '*', True)

    for path in train_ls_clahe_list:
        train_ls_clahe += glob(path, '*', True)

    for path in valid_ls_original_list:
        valid_ls_original += glob(path, '*', True)

    for path in valid_ls_mask_list:
        valid_ls_mask += glob(path, '*', True)

    for path in valid_ls_clahe_list:
        valid_ls_clahe += glob(path, '*', True)

    # 학습 및 검증 데이터셋 길이 출력
    print('Training Original list:', len(train_ls_original))
    print('Training Mask list:', len(train_ls_mask))
    print('Training CLAHE list:', len(train_ls_clahe))

    print('Validation Original list:', len(valid_ls_original))
    print('Validation Mask list:', len(valid_ls_mask))
    print('Validation CLAHE list:', len(valid_ls_clahe))

    pred_step = 1
    mean = [0.5, 0.5, 0.5]
    std = [0.5, 0.5, 0.5]
    os.makedirs(args.save_weight_dir, exist_ok=True)
    os.makedirs(args.log_dir, exist_ok=True)

    writer = SummaryWriter(join(args.log_dir, 'SR_Stage_4%s' % datetime.now().strftime("%Y%m%d-%H%M%S")))

    # Initialize the model
    print('Initializing model...')
    gen = build_model(config).cuda()
    # gen = Generator7(pred_step, device=0).cuda(0)
    dis = MsImageDis().cuda()
    # fake_pool = ImagePool(500)
    # real_pool = ImagePool(500)

    opt_gen = optim.Adam(gen.parameters(), lr=args.lr / 2, betas=(0, 0.9), weight_decay=1e-4)
    opt_dis = optim.Adam(dis.parameters(), lr=args.lr * 2, betas=(0, 0.9), weight_decay=1e-4)

    # Load pre-trained weight
    if args.load_pretrain:
        start_epoch = 320
        print(f'Loading model weight...at epoch {start_epoch}')
        gen.load_state_dict(torch.load(join(args.load_weight_dir, f'Gen_former_{start_epoch}.pt')))
        dis.load_state_dict(torch.load(join(args.load_weight_dir, f'Dis_former_{start_epoch}.pt')))
    else:
        start_epoch = 0

    # Load data
    print('Loading data...')
    # transformations = transforms.Compose([ToTensor(), Normalize(mean, std)])
    transformations = transforms.Compose(
        [torchvision.transforms.RandomResizedCrop((192, 192), scale=(0.8, 1.2), ratio=(0.75, 1.3333333333333333), ),
         CenterCrop(192), ToTensor(), Normalize(mean, std)])  # augmentation
    # train_data = torch.load(args.train_data_dir)
    # train_dataset = TensorDataset(train_data['gt'], train_data['mask'], train_data['iner'])
    # train_dataset = TensorDataset(train_data['gt'], train_data['mask'])
    # train_loader = torch.utils.data.DataLoader(dataset=train_dataset, batch_size=args.train_batch_size, shuffle=True)
    train_data = dataset_norm(root=args.train_data_dir, transforms=transformations, imgSize=192, inputsize=128,
                              imglist1=train_ls_original,  # First list of images
                              imglist2=train_ls_mask,  # Second list of images
                              imglist3=train_ls_clahe)   # 24.09.20 수정
    train_loader = DataLoader(train_data, batch_size=args.train_batch_size, shuffle=True, num_workers=4)
    print('train data: %d images' % (len(train_loader.dataset)))

    valid_data = dataset_norm(root=args.train_data_dir, transforms=transformations, imgSize=192, inputsize=128,
                              imglist1=valid_ls_original,  # First list of images
                              imglist2=valid_ls_mask,  # Second list of images
                              imglist3=valid_ls_clahe)  # Third list of images)
    valid_loader = DataLoader(valid_data, batch_size=args.train_batch_size, shuffle=True, num_workers=4)
    print('valid data: %d images' % (len(valid_loader.dataset)))
    # if args.test_flag:
    #     test_data = dataset_around(root=args.test_data_dir, transforms=transformations, crop='center', imgSize=128)
    #     test_loader = DataLoader(test_data, batch_size=args.test_batch_size, shuffle=False)
    #     print('test data: %d images' % (len(test_loader.dataset)))

    # Train & test the model
    for epoch in range(start_epoch + 1, 1 + args.epochs):
        print("----Start training[%d / %d]----" % (epoch, args.epochs))
        # train(gen, dis, fake_pool, real_pool, opt_gen, opt_dis, epoch, train_loader, writer)

        train(gen, dis, opt_gen, opt_dis, epoch, train_loader, writer) 

        # if args.test_flag:
        #     print("----Start testing[%d]----" % epoch)
        #     test(gen, dis, epoch, test_loader, writer)

        # Update the valid function to iterate over the tqdm-wrapped loader
        valid(gen, dis, opt_gen, opt_dis, epoch, valid_loader, writer)

        # Save the model weight every 10 epochs
        if (epoch % 10) == 0:
            torch.save(gen.state_dict(), join(args.save_weight_dir, 'Gen_former_%d.pt' % epoch))
            torch.save(dis.state_dict(), join(args.save_weight_dir, 'Dis_former_%d.pt' % epoch))

    writer.close()
