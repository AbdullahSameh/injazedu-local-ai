<?php

/*
 * Arabic validation messages for the rules the panel's forms use (`tg-panel-bilingual-plan.md`
 * §2). Any rule not listed here falls back to Laravel's English line. `:attribute` is the
 * field's own (already translated) label.
 */
return [

    'date' => 'يجب أن يكون حقل :attribute تاريخاً صالحاً.',
    'email' => 'يجب أن يكون حقل :attribute عنوان بريد إلكتروني صالحاً.',
    'in' => 'القيمة المختارة في حقل :attribute غير صالحة.',
    'integer' => 'يجب أن يكون حقل :attribute عدداً صحيحاً.',
    'max' => [
        'array' => 'يجب ألا يحتوي حقل :attribute على أكثر من :max عناصر.',
        'file' => 'يجب ألا يتجاوز حجم حقل :attribute :max كيلوبايت.',
        'numeric' => 'يجب ألا يتجاوز حقل :attribute القيمة :max.',
        'string' => 'يجب ألا يتجاوز حقل :attribute :max حرفاً.',
    ],
    'min' => [
        'array' => 'يجب أن يحتوي حقل :attribute على :min عناصر على الأقل.',
        'file' => 'يجب أن يكون حجم حقل :attribute :min كيلوبايت على الأقل.',
        'numeric' => 'يجب أن يكون حقل :attribute :min على الأقل.',
        'string' => 'يجب أن يكون حقل :attribute :min أحرف على الأقل.',
    ],
    'numeric' => 'يجب أن يكون حقل :attribute رقماً.',
    'required' => 'حقل :attribute مطلوب.',
    'string' => 'يجب أن يكون حقل :attribute نصاً.',
    'unique' => 'قيمة حقل :attribute مستخدمة من قبل.',
    'url' => 'يجب أن يكون حقل :attribute رابطاً صالحاً.',

];
