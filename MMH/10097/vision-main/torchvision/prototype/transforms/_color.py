import collections.abc
from typing import Any, Dict, Optional, Sequence, Tuple, TypeVar, Union

import PIL.Image
import torch
from torchvision.prototype import features
from torchvision.prototype.transforms import functional as F, Transform
from torchvision.transforms import functional as _F

from ._transform import _RandomApplyTransform
from ._utils import get_image_dimensions, is_simple_tensor, query_image

T = TypeVar("T", features.Image, torch.Tensor, PIL.Image.Image)


class ColorJitter(Transform):
    def __init__(
        self,
        brightness: Optional[Union[float, Sequence[float]]] = None,
        contrast: Optional[Union[float, Sequence[float]]] = None,
        saturation: Optional[Union[float, Sequence[float]]] = None,
        hue: Optional[Union[float, Sequence[float]]] = None,
    ) -> None:
        super().__init__()
        self.brightness = self._check_input(brightness, "brightness")
        self.contrast = self._check_input(contrast, "contrast")
        self.saturation = self._check_input(saturation, "saturation")
        self.hue = self._check_input(hue, "hue", center=0, bound=(-0.5, 0.5), clip_first_on_zero=False)

    def _check_input(
        self,
        value: Optional[Union[float, Sequence[float]]],
        name: str,
        center: float = 1.0,
        bound: Tuple[float, float] = (0, float("inf")),
        clip_first_on_zero: bool = True,
    ) -> Optional[Tuple[float, float]]:
        if value is None:
            return None

        if isinstance(value, float):
            if value < 0:
                raise ValueError(f"If {name} is a single number, it must be non negative.")
            value = [center - value, center + value]
            if clip_first_on_zero:
                value[0] = max(value[0], 0.0)
        elif isinstance(value, collections.abc.Sequence) and len(value) == 2:
            if not bound[0] <= value[0] <= value[1] <= bound[1]:
                raise ValueError(f"{name} values should be between {bound}")
        else:
            raise TypeError(f"{name} should be a single number or a sequence with length 2.")

        return None if value[0] == value[1] == center else (float(value[0]), float(value[1]))

    @staticmethod
    def _generate_value(left: float, right: float) -> float:
        return float(torch.distributions.Uniform(left, right).sample())

    def _get_params(self, sample: Any) -> Dict[str, Any]:
        fn_idx = torch.randperm(4)

        b = None if self.brightness is None else self._generate_value(self.brightness[0], self.brightness[1])
        c = None if self.contrast is None else self._generate_value(self.contrast[0], self.contrast[1])
        s = None if self.saturation is None else self._generate_value(self.saturation[0], self.saturation[1])
        h = None if self.hue is None else self._generate_value(self.hue[0], self.hue[1])

        return dict(fn_idx=fn_idx, brightness_factor=b, contrast_factor=c, saturation_factor=s, hue_factor=h)

    def _transform(self, inpt: Any, params: Dict[str, Any]) -> Any:
        output = inpt
        brightness_factor = params["brightness_factor"]
        contrast_factor = params["contrast_factor"]
        saturation_factor = params["saturation_factor"]
        hue_factor = params["hue_factor"]
        for fn_id in params["fn_idx"]:
            if fn_id == 0 and brightness_factor is not None:
                output = F.adjust_brightness(output, brightness_factor=brightness_factor)
            elif fn_id == 1 and contrast_factor is not None:
                output = F.adjust_contrast(output, contrast_factor=contrast_factor)
            elif fn_id == 2 and saturation_factor is not None:
                output = F.adjust_saturation(output, saturation_factor=saturation_factor)
            elif fn_id == 3 and hue_factor is not None:
                output = F.adjust_hue(output, hue_factor=hue_factor)
        return output


class _RandomChannelShuffle(Transform):
    def _get_params(self, sample: Any) -> Dict[str, Any]:
        image = query_image(sample)
        num_channels, _, _ = get_image_dimensions(image)
        return dict(permutation=torch.randperm(num_channels))

    def _transform(self, inpt: Any, params: Dict[str, Any]) -> Any:
        if not (isinstance(inpt, (features.Image, PIL.Image.Image)) or is_simple_tensor(inpt)):
            return inpt

        image = inpt
        if isinstance(inpt, PIL.Image.Image):
            image = _F.pil_to_tensor(image)

        output = image[..., params["permutation"], :, :]

        if isinstance(inpt, features.Image):
            output = features.Image.new_like(inpt, output, color_space=features.ColorSpace.OTHER)
        elif isinstance(inpt, PIL.Image.Image):
            output = _F.to_pil_image(output)

        return output


class RandomPhotometricDistort(Transform):
    def __init__(
        self,
        contrast: Tuple[float, float] = (0.5, 1.5),
        saturation: Tuple[float, float] = (0.5, 1.5),
        hue: Tuple[float, float] = (-0.05, 0.05),
        brightness: Tuple[float, float] = (0.875, 1.125),
        p: float = 0.5,
    ):
        super().__init__()
        self._brightness = ColorJitter(brightness=brightness)
        self._contrast = ColorJitter(contrast=contrast)
        self._hue = ColorJitter(hue=hue)
        self._saturation = ColorJitter(saturation=saturation)
        self._channel_shuffle = _RandomChannelShuffle()
        self.p = p

    def _get_params(self, sample: Any) -> Dict[str, Any]:
        return dict(
            zip(
                ["brightness", "contrast1", "saturation", "hue", "contrast2", "channel_shuffle"],
                torch.rand(6) < self.p,
            ),
            contrast_before=torch.rand(()) < 0.5,
        )

    def _transform(self, inpt: Any, params: Dict[str, Any]) -> Any:
        if params["brightness"]:
            inpt = self._brightness(inpt)
        if params["contrast1"] and params["contrast_before"]:
            inpt = self._contrast(inpt)
        if params["saturation"]:
            inpt = self._saturation(inpt)
        if params["saturation"]:
            inpt = self._saturation(inpt)
        if params["contrast2"] and not params["contrast_before"]:
            inpt = self._contrast(inpt)
        if params["channel_shuffle"]:
            inpt = self._channel_shuffle(inpt)
        return inpt


class RandomEqualize(_RandomApplyTransform):
    def __init__(self, p: float = 0.5):
        super().__init__(p=p)

    def _transform(self, inpt: Any, params: Dict[str, Any]) -> Any:
        return F.equalize(inpt)
