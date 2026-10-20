"""Seven-channel U-Net with a torchvision ResNet-18 encoder."""
import torch
from torch import nn
from torch.nn import functional as F
from torchvision.models import resnet18, ResNet18_Weights


class DecoderBlock(nn.Module):
    def __init__(self, incoming, skip, outgoing):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(incoming + skip, outgoing, 3, padding=1, bias=False),
            nn.GroupNorm(8, outgoing), nn.ReLU(inplace=True),
            nn.Conv2d(outgoing, outgoing, 3, padding=1, bias=False),
            nn.GroupNorm(8, outgoing), nn.ReLU(inplace=True))

    def forward(self, x, skip):
        x = F.interpolate(x, size=skip.shape[-2:], mode="bilinear", align_corners=False)
        return self.layers(torch.cat((x, skip), dim=1))


class FloodUNet(nn.Module):
    def __init__(self, in_channels=7, pretrained=False):
        super().__init__()
        encoder = resnet18(weights=ResNet18_Weights.DEFAULT if pretrained else None)
        original = encoder.conv1.weight.detach().clone()
        encoder.conv1 = nn.Conv2d(in_channels, 64, 7, stride=2, padding=3, bias=False)
        if pretrained:
            # RGB weights provide initialization only; these inputs are not RGB.
            with torch.no_grad():
                encoder.conv1.weight.copy_(original.mean(1, keepdim=True).repeat(1, in_channels, 1, 1) * (3 / in_channels))
        self.encoder = encoder
        self.encoder.fc = nn.Identity()
        self.d4 = DecoderBlock(512, 256, 128)
        self.d3 = DecoderBlock(128, 128, 64)
        self.d2 = DecoderBlock(64, 64, 32)
        self.d1 = DecoderBlock(32, 64, 16)
        self.head = nn.Sequential(nn.Conv2d(16, 16, 3, padding=1), nn.ReLU(), nn.Conv2d(16, 1, 1))

    def forward(self, x):
        shape = x.shape[-2:]
        e = self.encoder
        a = e.relu(e.bn1(e.conv1(x)))
        b = e.layer1(e.maxpool(a))
        c = e.layer2(b)
        d = e.layer3(c)
        z = e.layer4(d)
        z = self.d1(self.d2(self.d3(self.d4(z, d), c), b), a)
        return self.head(F.interpolate(z, size=shape, mode="bilinear", align_corners=False))


def masked_loss(logits, target, valid):
    """Ignore -1 before BCE; ignore pixels in both BCE and soft Dice."""
    if not valid.any():
        raise ValueError("Batch has no supervised pixels")
    y = torch.where(valid, target, 0).float()
    bce = F.binary_cross_entropy_with_logits(logits, y, reduction="none")[valid].mean()
    p = logits.sigmoid()[valid]
    truth = y[valid]
    dice = 1 - (2 * (p * truth).sum() + 1) / (p.sum() + truth.sum() + 1)
    return bce + dice
